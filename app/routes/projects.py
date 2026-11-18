from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.db import SessionLocal
from core.github_client import (
    GitHubClientError,
    create_issue,
    edit_issue_title,
    get_issue,
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
def get_issues(project_id: int, state: Literal["open", "closed", "all"] = "open"):
    with SessionLocal() as session:
        project = session.get(Project, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")
        return list_issues(project.github_repo, state)


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


def _subtask_summaries(session, project: Project, number: int) -> list[dict]:
    subtasks = (
        session.query(Subtask)
        .filter_by(project_id=project.id, github_issue_number=number)
        .order_by(Subtask.id)
        .all()
    )
    return [
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


def _get_project_or_404(session, project_id: int) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


@router.get("/{project_id}/issues/{number}")
def get_issue_detail(project_id: int, number: int):
    with SessionLocal() as session:
        project = _get_project_or_404(session, project_id)
        issue = get_issue(project.github_repo, number)
        issue["subtasks"] = _subtask_summaries(session, project, number)
        return issue


@router.get("/{project_id}/issues/{number}/subtasks")
def get_issue_subtasks(project_id: int, number: int):
    """画面の自動更新用にDB上のサブタスク一覧を返す（GitHubへは問い合わせない）"""
    with SessionLocal() as session:
        project = _get_project_or_404(session, project_id)
        return _subtask_summaries(session, project, number)
