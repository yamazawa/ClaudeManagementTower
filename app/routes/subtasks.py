from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

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
    get_pr_state,
    reopen_pr,
)
from core.models import ExecutionJob, Project, Subtask
from core.pr_sync import lifecycle_state_from_pr

router = APIRouter(prefix="/api/subtasks")

# クローズ可能な（未解決の）MRのlifecycle_state
OPEN_LIFECYCLE_STATES = ("draft", "in_review")


class CreateSubtaskRequest(BaseModel):
    project_id: int
    github_issue_number: int
    title: str
    instruction: str = ""


def _create_branch_and_draft_pr(
    project: Project,
    issue_number: int,
    title: str,
    instruction: str,
    slug_suffix: int,
) -> tuple[str, dict]:
    slug = slugify(title) or "subtask"
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


@router.post("")
def create_subtask(payload: CreateSubtaskRequest):
    with SessionLocal() as session:
        project = session.get(Project, payload.project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")

        existing_count = (
            session.query(Subtask)
            .filter_by(
                project_id=project.id,
                github_issue_number=payload.github_issue_number,
            )
            .count()
        )

        try:
            branch_name, pr = _create_branch_and_draft_pr(
                project,
                payload.github_issue_number,
                payload.title,
                payload.instruction,
                existing_count + 1,
            )
        except (GitClientError, GitHubClientError) as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        subtask = Subtask(
            project_id=project.id,
            github_issue_number=payload.github_issue_number,
            title=payload.title,
            instruction=payload.instruction,
            branch_name=branch_name,
            github_pr_number=pr["number"],
            lifecycle_state="draft",
        )
        session.add(subtask)
        session.commit()

        return {
            "id": subtask.id,
            "branch_name": subtask.branch_name,
            "github_pr_number": subtask.github_pr_number,
            "pr_url": pr["url"],
            "lifecycle_state": subtask.lifecycle_state,
        }


class UpdateSubtaskTitleRequest(BaseModel):
    title: str


@router.patch("/{subtask_id}")
def update_subtask_title(subtask_id: int, payload: UpdateSubtaskTitleRequest):
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="title is empty")
    with SessionLocal() as session:
        subtask = session.get(Subtask, subtask_id)
        if subtask is None:
            raise HTTPException(status_code=404, detail="subtask not found")
        project = session.get(Project, subtask.project_id)

        if subtask.github_pr_number is not None:
            try:
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
        if subtask.lifecycle_state not in OPEN_LIFECYCLE_STATES:
            raise HTTPException(status_code=409, detail="未解決のMRではありません")
        try:
            if subtask.github_pr_number is not None:
                close_pr(project.github_repo, subtask.github_pr_number)
        except GitHubClientError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        subtask.lifecycle_state = "closed"
        session.commit()
        return {"id": subtask.id, "lifecycle_state": subtask.lifecycle_state}


def _reopen_pr_and_get_state(project: Project, pr_number: int | None) -> str:
    if pr_number is None:
        return "draft"
    reopen_pr(project.github_repo, pr_number)
    return lifecycle_state_from_pr(get_pr_state(project.github_repo, pr_number))


@router.post("/{subtask_id}/reopen")
def reopen_subtask(subtask_id: int):
    """クローズ済のMRを再開する

    再開後の状態はPRのDraft有無から決める。
    """
    with SessionLocal() as session:
        subtask, project = _get_subtask_and_project(session, subtask_id)
        if subtask.lifecycle_state != "closed":
            raise HTTPException(status_code=409, detail="クローズ済のMRではありません")
        try:
            new_state = _reopen_pr_and_get_state(project, subtask.github_pr_number)
        except GitHubClientError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        subtask.lifecycle_state = new_state
        session.commit()
        return {"id": subtask.id, "lifecycle_state": subtask.lifecycle_state}


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
