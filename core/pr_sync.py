import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor

from core.config import settings
from core.db import SessionLocal
from core.github_client import list_pull_request_states
from core.lifecycle import LifecycleState
from core.models import Project, Subtask

logger = logging.getLogger(__name__)

# マージ済は終端状態のため同期対象から外す
SYNC_TARGET_STATES = (*LifecycleState.OPEN_STATES, LifecycleState.CANCELED)
# Issueと紐づくブランチ名の命名規則（issue-{Issue番号}-{内容}）
ISSUE_BRANCH_PATTERN = re.compile(r"^issue-(\d+)-")


def lifecycle_state_from_pr(pr: dict) -> str:
    if pr.get("mergedAt"):
        return LifecycleState.MERGED
    if pr.get("state") == "CLOSED":
        return LifecycleState.CANCELED
    if pr.get("isDraft"):
        return LifecycleState.DRAFT
    return LifecycleState.RESOLVED


def _sync_targets(session, project_id: int) -> list[Subtask]:
    return (
        session.query(Subtask)
        .filter(
            Subtask.project_id == project_id,
            Subtask.github_pr_number.isnot(None),
            Subtask.lifecycle_state.in_(SYNC_TARGET_STATES),
        )
        .all()
    )


def linked_issue_number(pr: dict, repo: str) -> int | None:
    """PRの紐づくIssue番号

    同一リポジトリのクローズ対象Issueを優先し、無ければブランチ名の命名規則から読み取る。
    特定できない場合はNoneを返す。
    """
    refs = [
        ref["number"]
        for ref in pr.get("closingIssuesReferences") or []
        if _ref_repo(ref).lower() == repo.lower()
    ]
    if refs:
        return refs[0]
    match = ISSUE_BRANCH_PATTERN.match(pr.get("headRefName") or "")
    return int(match.group(1)) if match else None


def _ref_repo(ref: dict) -> str:
    repository = ref.get("repository") or {}
    owner = (repository.get("owner") or {}).get("login", "")
    return f"{owner}/{repository.get('name', '')}"


def _update_states(subtasks: list[Subtask], prs: dict[int, dict]) -> list[dict]:
    updated = []
    for subtask in subtasks:
        pr = prs.get(subtask.github_pr_number)
        new_state = lifecycle_state_from_pr(pr) if pr else subtask.lifecycle_state
        if new_state == subtask.lifecycle_state:
            continue
        subtask.lifecycle_state = new_state
        updated.append({"subtask_id": subtask.id, "lifecycle_state": new_state})
    return updated


def _import_untracked_prs(session, project: Project, prs: list[dict]) -> list[dict]:
    """管理塔外で作成されたPRをサブタスクとして取り込む

    PR番号・ブランチ名のどちらかが既存サブタスクと一致するPRは取り込まない。
    紐づくIssueを特定できないPRも取り込まない。
    """
    tracked = session.query(Subtask).filter_by(project_id=project.id).all()
    tracked_numbers = {s.github_pr_number for s in tracked}
    tracked_branches = {s.branch_name for s in tracked}
    untracked = [
        pr for pr in prs
        if pr["number"] not in tracked_numbers and pr.get("headRefName") not in tracked_branches
    ]
    subtasks = [
        _subtask_from_pr(project, pr, number)
        for pr in untracked
        if (number := linked_issue_number(pr, project.github_repo)) is not None
    ]
    session.add_all(subtasks)
    session.flush()
    return [{"subtask_id": s.id, "lifecycle_state": s.lifecycle_state} for s in subtasks]


def _subtask_from_pr(project: Project, pr: dict, issue_number: int) -> Subtask:
    return Subtask(
        project_id=project.id,
        github_issue_number=issue_number,
        title=pr.get("title") or "",
        instruction="",
        branch_name=pr.get("headRefName") or "",
        github_pr_number=pr["number"],
        lifecycle_state=lifecycle_state_from_pr(pr),
    )


def sync_project_states(session, project: Project, prs: list[dict]) -> list[dict]:
    """PR状態をサブタスクに反映する

    管理塔外で作成されたPRも、紐づくIssueのサブタスクとして取り込む。
    状態を変更・新規作成したサブタスクのIDと状態を返す。
    """
    subtasks = _sync_targets(session, project.id)
    updated = _update_states(subtasks, {pr["number"]: pr for pr in prs})
    imported = _import_untracked_prs(session, project, prs)
    session.commit()
    return updated + imported


def _project_ids_by_repo(factory) -> dict[str, list[int]]:
    with factory() as session:
        projects = session.query(Project).order_by(Project.id).all()
    repos: dict[str, list[int]] = {}
    for project in projects:
        repos.setdefault(project.github_repo, []).append(project.id)
    return repos


def _sync_repo(factory, repo: str, project_ids: list[int]) -> list[dict]:
    """1リポジトリのPR状態を、そのリポジトリのプロジェクトへ反映する

    DBセッションはリポジトリごとに分け、他スレッドと共有しない。
    """
    prs = list_pull_request_states(repo)
    with factory() as session:
        projects = session.query(Project).filter(Project.id.in_(project_ids)).order_by(Project.id)
        return [u for p in projects.all() for u in sync_project_states(session, p, prs)]


def _sync_repo_safely(factory, repo: str, project_ids: list[int]) -> list[dict]:
    try:
        return _sync_repo(factory, repo, project_ids)
    except Exception as exc:  # noqa: BLE001
        # 1リポジトリの失敗で他のリポジトリの同期を止めない
        logger.warning("%s のPR状態の同期に失敗しました: %s", repo, exc)
        return []


def sync_all_projects(session_factory=None) -> list[dict]:
    """全リポジトリのPR状態をリポジトリごとに並行して同期する

    失敗したリポジトリはログに残して読み飛ばす。
    """
    factory = session_factory or SessionLocal
    repos = _project_ids_by_repo(factory)
    with ThreadPoolExecutor(max_workers=settings.pr_sync_max_workers) as executor:
        results = executor.map(lambda item: _sync_repo_safely(factory, *item), repos.items())
        return [u for result in results for u in result]


def mark_prs_merged(repo: str, pr_numbers: list[int], session_factory=None) -> None:
    """アプリからマージしたPRのサブタスクを即時にマージ済へ更新する"""
    if not pr_numbers:
        return
    factory = session_factory or SessionLocal
    with factory() as session:
        project_ids = [p.id for p in session.query(Project).filter_by(github_repo=repo)]
        session.query(Subtask).filter(
            Subtask.project_id.in_(project_ids),
            Subtask.github_pr_number.in_(pr_numbers),
        ).update({"lifecycle_state": LifecycleState.MERGED}, synchronize_session=False)
        session.commit()


def _sync_loop(stop_event: threading.Event, interval_seconds: float) -> None:
    while not stop_event.is_set():
        try:
            sync_all_projects()
        except Exception as exc:  # noqa: BLE001
            # GitHub・DBの一時的な失敗で同期ループを止めない
            logger.warning("PR状態の同期に失敗しました: %s", exc)
        stop_event.wait(interval_seconds)


def start_sync_loop(interval_seconds: float) -> threading.Event:
    """PR状態の定期同期をバックグラウンドで開始する

    返したEventをsetすると停止する。
    """
    stop_event = threading.Event()
    thread = threading.Thread(
        target=_sync_loop, args=(stop_event, interval_seconds), daemon=True
    )
    thread.start()
    return stop_event
