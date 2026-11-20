"""デプロイしたソースに含まれるマージ済MRをDeployedにする

デプロイ先のチェックアウト中のHEADに、PRのマージコミットが含まれるかで判定する。
"""

from core.db import SessionLocal
from core.git_client import is_commit_in_head
from core.github_client import GitHubClientError, get_pr_merge_commit, list_merged_pull_requests
from core.lifecycle import LifecycleState
from core.models import Project, Subtask


def mark_deployed(project_id: int, repo_path: str, session_factory=None) -> list[int]:
    """マージ済MRのうち、デプロイしたソースに含まれるものをDeployedにする

    更新したサブタスクのIDを返す。
    """
    factory = session_factory or SessionLocal
    with factory() as session:
        project = session.get(Project, project_id)
        if project is None:
            return []
        subtasks = _merged_subtasks(session, project_id)
        if not subtasks:
            return []
        commits = _merge_commits(project.github_repo, subtasks)
        deployed = [
            s for s in subtasks
            if (commit := commits.get(s.github_pr_number)) and is_commit_in_head(repo_path, commit)
        ]
        for subtask in deployed:
            subtask.lifecycle_state = LifecycleState.DEPLOYED
        session.commit()
        return [s.id for s in deployed]


def mark_deployed_for_repo(github_repo: str, repo_path: str, session_factory=None) -> list[int]:
    """同じGitHubリポジトリを対象とする全リポジトリ登録について、Deployedにする"""
    factory = session_factory or SessionLocal
    with factory() as session:
        project_ids = [p.id for p in session.query(Project).filter_by(github_repo=github_repo)]
    return [i for pid in project_ids for i in mark_deployed(pid, repo_path, factory)]


def _merged_subtasks(session, project_id: int) -> list[Subtask]:
    return (
        session.query(Subtask)
        .filter(
            Subtask.project_id == project_id,
            Subtask.github_pr_number.isnot(None),
            Subtask.lifecycle_state == LifecycleState.MERGED,
        )
        .all()
    )


def _merge_commits(repo: str, subtasks: list[Subtask]) -> dict[int, str]:
    """PR番号ごとのマージコミット

    一覧の取得件数上限から漏れたPRは個別に取得する。
    """
    commits = {
        pr["number"]: (pr.get("mergeCommit") or {}).get("oid")
        for pr in list_merged_pull_requests(repo)
    }
    missing = {s.github_pr_number for s in subtasks} - commits.keys()
    commits.update({number: _get_merge_commit_or_none(repo, number) for number in missing})
    return commits


def _get_merge_commit_or_none(repo: str, number: int) -> str | None:
    # 1件の取得失敗で他のMRの判定を止めないよう、判定不能として扱う
    try:
        return get_pr_merge_commit(repo, number)
    except GitHubClientError:
        return None
