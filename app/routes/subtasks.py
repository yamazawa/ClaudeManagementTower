from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from pydantic import BaseModel

from core.attachments import AttachmentError, list_attachments, save_attachment
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
    edit_pr_title,
    get_issue,
    get_pr_state,
    reopen_pr,
)
from core.lifecycle import LifecycleState
from core.models import ExecutionJob, Project, Subtask
from core.mr_naming import compose_mr_title, next_default_suffix
from core.pr_merger import PrMergeError, merge_pr_with_update
from core.pr_sync import lifecycle_state_from_pr

router = APIRouter(prefix="/api/subtasks")

# 実行中とみなすジョブの状態（実行中はマージさせない）
ACTIVE_JOB_STATUSES = ("queued", "running")


class CreateSubtaskRequest(BaseModel):
    project_id: int
    github_issue_number: int
    # MR固有名（MR名のIssue名より後ろの部分）。空欄なら連番を割り当てる
    title: str = ""
    instruction: str = ""


def _create_branch_and_draft_pr(
    project: Project,
    issue_number: int,
    title: str,
    instruction: str,
    slug_suffix: int,
    slug_source: str | None = None,
) -> tuple[str, dict]:
    slug = slugify(slug_source or title) or "subtask"
    branch_name = f"issue-{issue_number}-{slug}-{slug_suffix}"
    worktree_path = f"{settings.worktree_base_dir}/{branch_name}"

    create_worktree(project.repo_path, branch_name, project.default_branch, worktree_path)
    commit_subtask_instruction(worktree_path, title, instruction)
    push_branch(worktree_path, branch_name)
    pr = create_draft_pr(
        repo=project.github_repo,
        base=project.default_branch,
        head=branch_name,
        title=title,
        body=f"Related to #{issue_number}",
    )
    return branch_name, pr


def _find_or_add_subtask(session, project_id: int, issue_number: int, branch_name: str) -> Subtask:
    """作成したPRのサブタスク行を返す

    PR作成直後に自動同期が管理塔外のPRとして取り込んでいる場合、その行を使う。
    """
    keys = {"project_id": project_id, "github_issue_number": issue_number, "branch_name": branch_name}
    subtask = session.query(Subtask).filter_by(**keys).first()
    if subtask is None:
        subtask = Subtask(**keys)
        session.add(subtask)
    return subtask


@router.post("")
def create_subtask(payload: CreateSubtaskRequest):
    with SessionLocal() as session:
        project = session.get(Project, payload.project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")

        existing_titles = [
            s.title
            for s in session.query(Subtask).filter_by(
                project_id=project.id,
                github_issue_number=payload.github_issue_number,
            )
        ]

        try:
            issue_title = get_issue(project.github_repo, payload.github_issue_number)["title"]
            suffix = payload.title.strip() or next_default_suffix(issue_title, existing_titles)
            title = compose_mr_title(issue_title, suffix)
            branch_name, pr = _create_branch_and_draft_pr(
                project,
                payload.github_issue_number,
                title,
                payload.instruction,
                len(existing_titles) + 1,
                slug_source=suffix,
            )
        except (GitClientError, GitHubClientError) as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        subtask = _find_or_add_subtask(
            session, project.id, payload.github_issue_number, branch_name
        )
        subtask.title = title
        subtask.instruction = payload.instruction
        subtask.github_pr_number = pr["number"]
        subtask.lifecycle_state = LifecycleState.DRAFT
        session.commit()

        return {
            "id": subtask.id,
            "title": subtask.title,
            "branch_name": subtask.branch_name,
            "github_pr_number": subtask.github_pr_number,
            "pr_url": pr["url"],
            "lifecycle_state": subtask.lifecycle_state,
        }


class UpdateSubtaskTitleRequest(BaseModel):
    # MR固有名（MR名のIssue名より後ろの部分）
    title: str


@router.patch("/{subtask_id}")
def update_subtask_title(subtask_id: int, payload: UpdateSubtaskTitleRequest):
    """MR名のMR固有名部分を変更する

    Issue名は最新のものをGitHubから取得して付け直す。
    """
    suffix = payload.title.strip()
    if not suffix:
        raise HTTPException(status_code=400, detail="title is empty")
    with SessionLocal() as session:
        subtask = session.get(Subtask, subtask_id)
        if subtask is None:
            raise HTTPException(status_code=404, detail="subtask not found")
        project = session.get(Project, subtask.project_id)

        try:
            issue_title = get_issue(project.github_repo, subtask.github_issue_number)["title"]
            title = compose_mr_title(issue_title, suffix)
            if subtask.github_pr_number is not None:
                edit_pr_title(project.github_repo, subtask.github_pr_number, title)
        except GitHubClientError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        subtask.title = title
        session.commit()
        return {"id": subtask.id, "title": subtask.title}


def _get_subtask_and_project(session, subtask_id: int) -> tuple[Subtask, Project]:
    subtask = session.get(Subtask, subtask_id)
    if subtask is None:
        raise HTTPException(status_code=404, detail="subtask not found")
    return subtask, session.get(Project, subtask.project_id)


@router.post("/{subtask_id}/close")
def close_subtask(subtask_id: int):
    """MRをクローズする

    マージ済のMRは閉じられないため拒否する。
    """
    with SessionLocal() as session:
        subtask, project = _get_subtask_and_project(session, subtask_id)
        if subtask.lifecycle_state not in LifecycleState.OPEN_STATES:
            raise HTTPException(status_code=409, detail="未解決のMRではありません")
        try:
            if subtask.github_pr_number is not None:
                close_pr(project.github_repo, subtask.github_pr_number)
        except GitHubClientError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        subtask.lifecycle_state = LifecycleState.CANCELED
        session.commit()
        return {"id": subtask.id, "lifecycle_state": subtask.lifecycle_state}


def _reopen_pr_and_get_state(project: Project, pr_number: int | None) -> str:
    if pr_number is None:
        return LifecycleState.DRAFT
    reopen_pr(project.github_repo, pr_number)
    return lifecycle_state_from_pr(get_pr_state(project.github_repo, pr_number))


@router.post("/{subtask_id}/reopen")
def reopen_subtask(subtask_id: int):
    """クローズ済のMRを再開する

    再開後の状態はPRのDraft有無から決める。
    """
    with SessionLocal() as session:
        subtask, project = _get_subtask_and_project(session, subtask_id)
        if subtask.lifecycle_state != LifecycleState.CANCELED:
            raise HTTPException(status_code=409, detail="クローズ済のMRではありません")
        try:
            new_state = _reopen_pr_and_get_state(project, subtask.github_pr_number)
        except GitHubClientError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        subtask.lifecycle_state = new_state
        session.commit()
        return {"id": subtask.id, "lifecycle_state": subtask.lifecycle_state}


def _has_active_job(session, subtask_id: int) -> bool:
    return (
        session.query(ExecutionJob)
        .filter_by(subtask_id=subtask_id)
        .filter(ExecutionJob.status.in_(ACTIVE_JOB_STATUSES))
        .first()
        is not None
    )


def _ensure_mergeable(session, subtask: Subtask) -> None:
    if subtask.lifecycle_state != LifecycleState.RESOLVED:
        raise HTTPException(status_code=409, detail="ResolvedのMRではありません")
    if subtask.github_pr_number is None:
        raise HTTPException(status_code=409, detail="PRが作成されていません")
    if _has_active_job(session, subtask.id):
        raise HTTPException(status_code=409, detail="実装の実行中はマージできません")


def _pr_refs(subtask: Subtask, project: Project) -> dict:
    return {
        "number": subtask.github_pr_number,
        "headRefName": subtask.branch_name,
        "baseRefName": project.default_branch,
    }


@router.post("/{subtask_id}/merge")
def merge_subtask(subtask_id: int):
    """MRをマージする

    Resolvedかつ実装の実行中でない場合のみ受け付ける。
    競合時はベースブランチを取り込み、Claudeで競合解決してからマージする。
    """
    with SessionLocal() as session:
        subtask, project = _get_subtask_and_project(session, subtask_id)
        _ensure_mergeable(session, subtask)
        try:
            merge_pr_with_update(
                project.github_repo,
                project.repo_path,
                settings.worktree_base_dir,
                _pr_refs(subtask, project),
            )
        except (GitClientError, GitHubClientError, PrMergeError) as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        subtask.lifecycle_state = LifecycleState.MERGED
        session.commit()
        return {"id": subtask.id, "lifecycle_state": subtask.lifecycle_state}


def _subtask_worktree_path(subtask_id: int) -> str:
    with SessionLocal() as session:
        subtask = session.get(Subtask, subtask_id)
        if subtask is None:
            raise HTTPException(status_code=404, detail="subtask not found")
        return f"{settings.worktree_base_dir}/{subtask.branch_name}"


@router.get("/{subtask_id}/attachments")
def get_attachments(subtask_id: int):
    return list_attachments(_subtask_worktree_path(subtask_id))


@router.post("/{subtask_id}/attachments")
async def upload_attachment(subtask_id: int, file: UploadFile):
    """実装指示の添付ファイルを保存する

    IDはS1、S2…の連番で割り当てる。
    """
    worktree_path = _subtask_worktree_path(subtask_id)
    if not Path(worktree_path).is_dir():
        raise HTTPException(status_code=409, detail="worktreeがありません")
    try:
        return save_attachment(worktree_path, file.filename or "", await file.read())
    except AttachmentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class ExecuteSubtaskRequest(BaseModel):
    instruction: str | None = None


@router.post("/{subtask_id}/execute")
def execute_subtask(subtask_id: int, payload: ExecuteSubtaskRequest | None = None):
    with SessionLocal() as session:
        subtask = session.get(Subtask, subtask_id)
        if subtask is None:
            raise HTTPException(status_code=404, detail="subtask not found")

        if payload is not None and payload.instruction:
            subtask.instruction = payload.instruction

        job = ExecutionJob(subtask_id=subtask_id, status="queued")
        session.add(job)
        session.commit()
        session.refresh(job)

        return {"job_id": job.id, "status": job.status}
