"""追加したリポジトリの管理用初期設定

Claude管理塔で管理するためのファイルを、Issue・MRを通してコミットする。
Issue・MRの作成からマージ・Issueのクローズまでを行い、管理塔の動作確認を兼ねる。
"""

import logging
from pathlib import Path

from core.config import settings
from core.deploy import mark_deployed_safely
from core.deploy_tracking import mark_deployed
from core.git_client import (
    GitClientError,
    commit_files,
    create_worktree,
    delete_local_branch,
    pull_latest,
    push_branch,
    remove_worktree,
)
from core.github_client import (
    close_issue,
    create_draft_pr,
    create_issue,
    mark_pr_ready,
    merge_pull_request,
)
from core.lifecycle import LifecycleState
from core.models import Project, Subtask
from core.mr_naming import compose_mr_title, number_label

logger = logging.getLogger(__name__)

SETUP_ISSUE_TITLE = "Claude監視塔の管理用初期設定"
SETUP_ISSUE_BODY = (
    "Claude監視塔で管理するための初期設定\n\n"
    "CLAUDE.md・.gitignoreを追加する。\n"
    "リポジトリ追加時に管理塔が自動で作成した。\n"
)
SETUP_BRANCH_SLUG = "claude-tower-setup"
CLAUDE_MD_PATH = "CLAUDE.md"
GITIGNORE_PATH = ".gitignore"
GITIGNORE_CONTENT = ".venv/\n.env\n"


def run_initial_setup(project_id: int, session_factory) -> dict:
    """初期設定のIssue・MRを作成し、マージしてIssueをクローズする

    後始末（worktree・ローカルブランチの削除）の失敗は、warningsとして返す。
    """
    with session_factory() as session:
        project = session.get(Project, project_id)
    issue_number = create_issue(project.github_repo, SETUP_ISSUE_TITLE, SETUP_ISSUE_BODY)["number"]
    branch_name = f"issue-{issue_number}-{SETUP_BRANCH_SLUG}"
    worktree_path = f"{settings.worktree_base_dir}/{project.name}-{branch_name}"
    _commit_setup_files(project, issue_number, branch_name, worktree_path)
    pr_number = _open_mr(session_factory, project, issue_number, branch_name)
    _merge_and_close(session_factory, project, issue_number, pr_number)
    warnings = _cleanup(project, worktree_path, branch_name)
    mark_deployed_safely(lambda: mark_deployed(project.id, project.repo_path, session_factory))
    return {"issue_number": issue_number, "pr_number": pr_number, "warnings": warnings}


def _commit_setup_files(project: Project, issue_number: int, branch_name: str, worktree_path: str) -> None:
    create_worktree(project.repo_path, branch_name, project.default_branch, worktree_path)
    Path(worktree_path, CLAUDE_MD_PATH).write_text(claude_md(project), encoding="utf-8")
    Path(worktree_path, GITIGNORE_PATH).write_text(GITIGNORE_CONTENT, encoding="utf-8")
    message = f"#{issue_number} [初期設定] Claude監視塔の管理用ファイルを追加"
    commit_files(worktree_path, [CLAUDE_MD_PATH, GITIGNORE_PATH], message)
    push_branch(worktree_path, branch_name)


def claude_md(project: Project) -> str:
    return (
        f"# {project.display_name} プロジェクト指示\n\n"
        f"{project.description}\n\n"
        "# 管理方法\n\n"
        "本リポジトリはClaude管理塔で管理する。\\\n"
        "Issue・MRの作成とマージは管理塔から行う。\\\n"
        "`.claude-tower/`配下には管理塔が使うファイルを置く。\n"
    )


def _open_mr(session_factory, project: Project, issue_number: int, branch_name: str) -> int:
    """PRを作成し、管理塔のMRとして登録する"""
    title = compose_mr_title(SETUP_ISSUE_TITLE, number_label(1))
    pr = create_draft_pr(
        repo=project.github_repo,
        base=project.default_branch,
        head=branch_name,
        title=title,
        body=f"Related to #{issue_number}",
    )
    keys = {"project_id": project.id, "github_issue_number": issue_number, "branch_name": branch_name}
    with session_factory() as session:
        # PR作成直後に自動同期が管理塔外のPRとして取り込んでいる場合、その行を使う
        subtask = session.query(Subtask).filter_by(**keys).first() or Subtask(**keys)
        subtask.title = title
        subtask.instruction = SETUP_ISSUE_BODY
        subtask.github_pr_number = pr["number"]
        subtask.lifecycle_state = LifecycleState.DRAFT
        session.add(subtask)
        session.commit()
    return pr["number"]


def _merge_and_close(session_factory, project: Project, issue_number: int, pr_number: int) -> None:
    mark_pr_ready(project.github_repo, pr_number)
    merge_pull_request(project.github_repo, pr_number)
    with session_factory() as session:
        subtask = session.query(Subtask).filter_by(project_id=project.id, github_pr_number=pr_number).one()
        subtask.lifecycle_state = LifecycleState.MERGED
        session.commit()
    close_issue(project.github_repo, issue_number)


def _cleanup(project: Project, worktree_path: str, branch_name: str) -> list[str]:
    """worktreeを削除し、マージ結果を取り込んでからローカルブランチを削除する"""
    steps = [
        ("worktreeの削除", lambda: remove_worktree(project.repo_path, worktree_path)),
        ("マージ結果の取り込み", lambda: pull_latest(project.repo_path, project.default_branch)),
        ("ローカルブランチの削除", lambda: delete_local_branch(project.repo_path, branch_name)),
    ]
    return [warning for label, step in steps if (warning := _run_cleanup_step(label, step))]


def _run_cleanup_step(label: str, step) -> str | None:
    try:
        step()
    except GitClientError as exc:
        logger.warning("初期設定の後始末（%s）に失敗しました: %s", label, exc)
        return f"{label}に失敗しました: {exc}"
    return None
