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
from core.github_client import GitHubClientError, create_draft_pr
from core.models import ExecutionJob, Project, Subtask

router = APIRouter(prefix="/api/subtasks")


class CreateSubtaskRequest(BaseModel):
    project_id: int
    github_issue_number: int
    title: str
    instruction: str


def _create_branch_and_draft_pr(
    project: Project,
    issue_number: int,
    title: str,
    instruction: str,
    slug_suffix: int,
) -> tuple[str, dict]:
    slug = slugify(title) or f"subtask-{slug_suffix}"
    branch_name = f"issue-{issue_number}-{slug}"
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
