from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.db import SessionLocal
from core.github_client import (
    GitHubClientError,
    create_issue,
    edit_issue_title,
    get_issue,
    get_pr,
    list_issues,
)
from core.models import ExecutionJob, Project, Report, Subtask

router = APIRouter(prefix="/api/projects")


def _latest_job_summary(session, subtask_id: int) -> dict | None:
    job = (
        session.query(ExecutionJob)
        .filter_by(subtask_id=subtask_id)
        .order_by(ExecutionJob.id.desc())
        .first()
    )
    if job is None:
        return None
    has_report = session.query(Report).filter_by(job_id=job.id).first() is not None
    return {"id": job.id, "status": job.status, "has_report": has_report}


class CreateIssueRequest(BaseModel):
    title: str
    body: str = ""


@router.get("")
def get_projects():
    with SessionLocal() as session:
        projects = session.query(Project).all()
        return [
            {
                "id": p.id,
                "name": p.name,
                "github_repo": p.github_repo,
                "default_branch": p.default_branch,
            }
            for p in projects
        ]


@router.get("/{project_id}/issues")
def get_issues(project_id: int):
    with SessionLocal() as session:
        project = session.get(Project, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")
        return list_issues(project.github_repo)


@router.post("/{project_id}/issues")
def create_project_issue(project_id: int, payload: CreateIssueRequest):
    with SessionLocal() as session:
        project = session.get(Project, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")

        try:
            return create_issue(project.github_repo, payload.title, payload.body)
        except GitHubClientError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc


class UpdateTitleRequest(BaseModel):
    title: str


@router.patch("/{project_id}/issues/{number}")
def update_issue_title(project_id: int, number: int, payload: UpdateTitleRequest):
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="title is empty")
    with SessionLocal() as session:
        project = session.get(Project, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")
        try:
            edit_issue_title(project.github_repo, number, title)
        except GitHubClientError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"number": number, "title": title}


@router.get("/{project_id}/issues/{number}")
def get_issue_detail(project_id: int, number: int):
    with SessionLocal() as session:
        project = session.get(Project, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")
        issue = get_issue(project.github_repo, number)
        subtasks = (
            session.query(Subtask)
            .filter_by(project_id=project.id, github_issue_number=number)
            .all()
        )
        issue["subtasks"] = [
            {
                "id": s.id,
                "title": s.title,
                "instruction": s.instruction,
                "lifecycle_state": s.lifecycle_state,
                "github_pr_number": s.github_pr_number,
                "pr_url": (
                    f"https://github.com/{project.github_repo}/pull/{s.github_pr_number}"
                    if s.github_pr_number
                    else None
                ),
                "latest_job": _latest_job_summary(session, s.id),
            }
            for s in subtasks
        ]
        return issue


def _lifecycle_state_from_pr(pr: dict) -> str:
    if pr.get("mergedAt"):
        return "merged"
    if pr.get("state") == "CLOSED":
        return "closed"
    if pr.get("isDraft"):
        return "draft"
    return "in_review"


@router.post("/{project_id}/sync")
def sync_project(project_id: int):
    with SessionLocal() as session:
        project = session.get(Project, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")

        subtasks = (
            session.query(Subtask)
            .filter(Subtask.project_id == project.id, Subtask.github_pr_number.isnot(None))
            .all()
        )
        updated = []
        for subtask in subtasks:
            pr = get_pr(project.github_repo, subtask.github_pr_number)
            new_state = _lifecycle_state_from_pr(pr)
            if new_state != subtask.lifecycle_state:
                subtask.lifecycle_state = new_state
                updated.append({"subtask_id": subtask.id, "lifecycle_state": new_state})
        session.commit()
        return {"updated": updated}
