"""Issue・MRの作成

管理塔の画面・アイデアマン・CLIタブで共通のIssue・MR作成処理を扱う。
MRはworktree作成・指示の記録・push・Draft PR作成を行い、DBに登録する。
IssueとMRを続けて作成する場合、高速化のためIssue作成とMR作成を並行して行う。
"""

import logging
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from uuid import uuid4

from sqlalchemy.orm import sessionmaker

from core.config import settings
from core.db import SessionLocal
from core.git_client import (
    GitClientError,
    commit_subtask_instruction,
    create_worktree,
    push_branch,
    slugify,
)
from core.github_client import (
    GitHubClientError,
    close_pr,
    create_draft_pr,
    edit_pr_body,
    get_issue,
)
from core.github_client import create_issue as create_github_issue
from core.lifecycle import LifecycleState
from core.models import Project, Subtask
from core.mr_naming import compose_mr_title, next_default_suffix
from core.subtask_rollback import (
    SubtaskCreationStage,
    describe_rollback_result,
    rollback_subtask_creation,
)

logger = logging.getLogger(__name__)

# 作成処理が投げるGit・GitHub操作の失敗
CREATION_ERRORS = (GitClientError, GitHubClientError)

# Issue作成と並行して作るMRのブランチ名の接頭辞（Issue番号の代わりに一意な識別子を続ける）
PENDING_BRANCH_PREFIX = "issue-new"
# ブランチ名に含める一意な識別子の長さ
UNIQUE_BRANCH_ID_LENGTH = 8
# Issue紐付け前のPR本文
PENDING_PR_BODY = "Issue紐付け待ち"
DEFAULT_BRANCH_SLUG = "subtask"

# 応答後に行う処理の登録先（処理と引数を受け取る）
RunLater = Callable[..., None]


class EmptyTitleError(ValueError):
    pass


def _run_in_thread(func: Callable, *args) -> None:
    threading.Thread(target=func, args=args, daemon=True).start()


def _normalize_title(title: str) -> str:
    value = title.strip()
    if not value:
        raise EmptyTitleError("タイトルが空です")
    return value


def create_issue(project: Project, title: str, body: str = "") -> dict:
    """Issueを作成する

    続けて行うMR作成でIssue名を再取得せずに済むよう、作成したIssue名も返す。
    """
    value = _normalize_title(title)
    issue = create_github_issue(project.github_repo, value, body)
    return {**issue, "title": value}


def create_mr(
    project: Project,
    issue_number: int,
    suffix: str = "",
    instruction: str = "",
    issue_title: str = "",
    unique_branch: bool = False,
    session_factory: sessionmaker = SessionLocal,
) -> dict:
    """既存IssueにMRを作成する

    MR固有名が空欄なら連番を割り当てる。
    Issue名の指定があればGitHubへの問い合わせを省略する。
    unique_branchを指定すると、ブランチ名に連番の代わりに一意な識別子を使う。
    """
    existing_titles = _existing_mr_titles(project.id, issue_number, session_factory)
    issue_title = issue_title.strip() or get_issue(project.github_repo, issue_number)["title"]
    suffix = suffix.strip() or next_default_suffix(issue_title, existing_titles)
    title = compose_mr_title(issue_title, suffix)
    branch_name, pr = _create_branch_and_draft_pr(
        project,
        issue_number,
        title,
        instruction,
        len(existing_titles) + 1,
        slug_source=suffix,
        unique_branch=unique_branch,
    )
    return _register_mr(project.id, issue_number, branch_name, title, instruction, pr, session_factory)


def _existing_mr_titles(project_id: int, issue_number: int, session_factory: sessionmaker) -> list[str]:
    with session_factory() as session:
        rows = session.query(Subtask).filter_by(project_id=project_id, github_issue_number=issue_number)
        return [s.title for s in rows]


def _create_branch_and_draft_pr(
    project: Project,
    issue_number: int,
    title: str,
    instruction: str,
    slug_suffix: int,
    slug_source: str | None = None,
    unique_branch: bool = False,
) -> tuple[str, dict]:
    if unique_branch:
        branch_name = _unique_branch_name(f"issue-{issue_number}")
    else:
        slug = slugify(slug_source or title) or DEFAULT_BRANCH_SLUG
        branch_name = f"issue-{issue_number}-{slug}-{slug_suffix}"
    pr = _push_draft_pr(project, branch_name, title, instruction, related_issue_body(issue_number))
    return branch_name, pr


def related_issue_body(issue_number: int) -> str:
    return f"Related to #{issue_number}"


def _push_draft_pr(project: Project, branch_name: str, title: str, instruction: str, body: str) -> dict:
    """worktreeを作成して指示を記録し、Draft PRを作成する

    途中で失敗した場合、完了した段階を取り消してから例外を投げ直す。
    後始末で残ったものは例外のメッセージに含める。
    """
    worktree_path = f"{settings.worktree_base_dir}/{branch_name}"
    completed: set[SubtaskCreationStage] = set()
    try:
        _run_creation_stages(project, branch_name, title, instruction, worktree_path, completed)
        return create_draft_pr(
            repo=project.github_repo,
            base=project.default_branch,
            head=branch_name,
            title=title,
            body=body,
        )
    except CREATION_ERRORS as exc:
        if not completed:
            raise
        leftovers = rollback_subtask_creation(project.repo_path, worktree_path, branch_name, completed)
        raise type(exc)(f"{exc}\n{describe_rollback_result(leftovers)}") from exc


def _run_creation_stages(
    project: Project,
    branch_name: str,
    title: str,
    instruction: str,
    worktree_path: str,
    completed: set[SubtaskCreationStage],
) -> None:
    """Draft PR作成前の段階を実行し、完了した段階をcompletedに記録する"""
    create_worktree(project.repo_path, branch_name, project.default_branch, worktree_path)
    completed.add(SubtaskCreationStage.WORKTREE_CREATED)
    commit_subtask_instruction(worktree_path, title, instruction)
    completed.add(SubtaskCreationStage.INSTRUCTION_COMMITTED)
    push_branch(worktree_path, branch_name)
    completed.add(SubtaskCreationStage.BRANCH_PUSHED)


def _unique_branch_name(head: str) -> str:
    """一意な識別子を含むブランチ名

    先頭部分（issue-{Issue番号}またはissue-new）の後ろに識別子を続ける。
    """
    unique_id = uuid4().hex[:UNIQUE_BRANCH_ID_LENGTH]
    return f"{head}-{unique_id}-{DEFAULT_BRANCH_SLUG}-1"


def _register_mr(
    project_id: int,
    issue_number: int,
    branch_name: str,
    title: str,
    instruction: str,
    pr: dict,
    session_factory: sessionmaker,
) -> dict:
    """作成したMRをDBに登録する

    PR作成直後に自動同期が管理塔外のPRとして取り込んでいる場合、その行を使う。
    """
    keys = {"project_id": project_id, "github_issue_number": issue_number, "branch_name": branch_name}
    with session_factory() as session:
        subtask = session.query(Subtask).filter_by(**keys).first()
        if subtask is None:
            subtask = Subtask(**keys)
            session.add(subtask)
        subtask.title = title
        subtask.instruction = instruction
        subtask.github_pr_number = pr["number"]
        subtask.lifecycle_state = LifecycleState.DRAFT
        session.commit()
        return _created_mr_response(subtask, pr["url"])


def _created_mr_response(subtask: Subtask, pr_url: str) -> dict:
    return {
        "id": subtask.id,
        "title": subtask.title,
        "branch_name": subtask.branch_name,
        "github_pr_number": subtask.github_pr_number,
        "pr_url": pr_url,
        "lifecycle_state": subtask.lifecycle_state,
    }


def create_pending_mr(project: Project, issue_title: str, instruction: str = "") -> dict:
    """Issue作成と並行して、Issue未紐付けの規定値MRを作成する

    Issue番号が未確定のため、ブランチ名はIssue番号の代わりに一意な識別子を使う。
    DBへの登録とIssueの紐付けは、Issue作成後にlink_pending_mrで行う。
    """
    issue_title = _normalize_title(issue_title)
    title = compose_mr_title(issue_title, next_default_suffix(issue_title, []))
    branch_name = _unique_branch_name(PENDING_BRANCH_PREFIX)
    pr = _push_draft_pr(project, branch_name, title, instruction, PENDING_PR_BODY)
    return {"title": title, "branch_name": branch_name, "github_pr_number": pr["number"], "pr_url": pr["url"]}


def link_pending_mr(
    project: Project,
    issue_number: int,
    pending: dict,
    instruction: str = "",
    run_later: RunLater = _run_in_thread,
    session_factory: sessionmaker = SessionLocal,
) -> dict:
    """Issue作成と並行して作成したMRをIssueに紐付けてDBへ登録する

    PR本文へのIssue番号の記載は、応答を待たせないようrun_laterで後から行う。
    """
    pr = {"number": pending["github_pr_number"], "url": pending["pr_url"]}
    created = _register_mr(
        project.id, issue_number, pending["branch_name"], pending["title"], instruction, pr, session_factory
    )
    run_later(link_pr_to_issue, project.github_repo, pr["number"], issue_number)
    return created


def link_pr_to_issue(repo: str, pr_number: int, issue_number: int) -> None:
    """PR本文にIssue番号を記載する

    管理塔上の紐付けはDB登録済のため、失敗はログ出力のみとする。
    """
    try:
        edit_pr_body(repo, pr_number, related_issue_body(issue_number))
    except GitHubClientError as exc:
        logger.warning("PR #%s のIssue #%s 紐付けに失敗しました: %s", pr_number, issue_number, exc)


def discard_pending_mr(project: Project, pending: dict) -> None:
    """Issue作成に失敗した場合に、並行して作成したMRをクローズする

    worktree・ブランチは残す。
    クローズの失敗はIssue作成の失敗を優先して伝えるため、ログ出力のみとする。
    """
    try:
        close_pr(project.github_repo, pending["github_pr_number"])
    except GitHubClientError as exc:
        logger.warning("PR #%s のクローズに失敗しました: %s", pending["github_pr_number"], exc)


def create_issue_with_mr(
    project: Project,
    title: str,
    body: str = "",
    instruction: str = "",
    run_later: RunLater = _run_in_thread,
    session_factory: sessionmaker = SessionLocal,
) -> dict:
    """IssueとMRを作成する

    高速化のため、Issue作成とMR作成を並行して行い、MRへのIssue紐付けは後から行う。
    Issue作成に失敗した場合は、並行して作成したMRをクローズして例外を投げ直す。
    MR作成のみ失敗した場合は、mrをNoneとしmr_errorに理由を返す。
    """
    value = _normalize_title(title)
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending_future = executor.submit(create_pending_mr, project, value, instruction)
        try:
            issue = create_issue(project, value, body)
        except Exception:
            _discard_pending_result(project, pending_future)
            raise
        try:
            pending = pending_future.result()
        except CREATION_ERRORS as exc:
            return {"issue": issue, "mr": None, "mr_error": str(exc)}
    mr = link_pending_mr(project, issue["number"], pending, instruction, run_later, session_factory)
    return {"issue": issue, "mr": mr, "mr_error": None}


def _discard_pending_result(project: Project, pending_future: Future) -> None:
    """並行して作成したMRの完了を待ってクローズする（作成も失敗していれば何もしない）"""
    if pending_future.exception() is None:
        discard_pending_mr(project, pending_future.result())
