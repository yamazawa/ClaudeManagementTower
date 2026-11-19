import threading

from core.db import SessionLocal
from core.github_client import list_pull_request_states
from core.lifecycle import LifecycleState
from core.models import Project, Subtask

# マージ済は終端状態のため同期対象から外す
SYNC_TARGET_STATES = (*LifecycleState.OPEN_STATES, LifecycleState.CANCELED)


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


def sync_project_states(session, project: Project) -> list[dict]:
    """PR状態をサブタスクに反映する

    同期対象が無い場合はGitHubへ問い合わせない。
    変更したサブタスクのIDと新状態を返す。
    """
    subtasks = _sync_targets(session, project.id)
    if not subtasks:
        return []
    prs = {pr["number"]: pr for pr in list_pull_request_states(project.github_repo)}
    updated = []
    for subtask in subtasks:
        pr = prs.get(subtask.github_pr_number)
        new_state = lifecycle_state_from_pr(pr) if pr else subtask.lifecycle_state
        if new_state == subtask.lifecycle_state:
            continue
        subtask.lifecycle_state = new_state
        updated.append({"subtask_id": subtask.id, "lifecycle_state": new_state})
    session.commit()
    return updated


def sync_all_projects(session_factory=None) -> list[dict]:
    factory = session_factory or SessionLocal
    with factory() as session:
        projects = session.query(Project).all()
        return [u for p in projects for u in sync_project_states(session, p)]


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
            print(f"[pr_sync] PR状態の同期に失敗しました: {exc}")
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
