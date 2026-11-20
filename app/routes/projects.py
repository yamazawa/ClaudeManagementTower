from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import case, func

from core.db import SessionLocal
from core.deploy import is_deploy_defined
from core.github_client import (
    GitHubClientError,
    close_issue,
    create_issue,
    edit_issue_title,
    edit_pr_title,
    get_issue,
    list_issues,
    reopen_issue,
)
from core.lifecycle import LifecycleState
from core.models import ExecutionJob, Project, Report, Subtask
from core.mr_naming import compose_mr_title, split_mr_title
from core.repo_catalog import describe_repo

router = APIRouter(prefix="/api/projects")

# Issueクローズを妨げる未解決MRのlifecycle_state
UNRESOLVED_LIFECYCLE_STATES = LifecycleState.OPEN_STATES
# Issue一覧のMR数で解決済とみなすlifecycle_state
RESOLVED_LIFECYCLE_STATES = LifecycleState.MERGED_STATES
# Issue一覧のMR数から除外するlifecycle_state（マージされずクローズ）
UNCOUNTED_LIFECYCLE_STATE = LifecycleState.CANCELED
# レビュー待ち・デプロイ待ちとみなすlifecycle_state
REVIEW_LIFECYCLE_STATE = LifecycleState.RESOLVED
UNDEPLOYED_LIFECYCLE_STATE = LifecycleState.MERGED
EMPTY_MR_COUNTS = {"resolved": 0, "unresolved": 0, "total": 0, "review": 0, "undeployed": 0}
# Issue一覧のレビューフィルタ（レビュー待ちMRを含むIssue）の値
ISSUE_FILTER_REVIEW = "review"


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
                **describe_repo(p.github_repo, p.name),
                "deploy_defined": is_deploy_defined(p.repo_path),
            }
            for p in projects
        ]


@router.get("/{project_id}/issues")
def get_issues(project_id: int, state: Literal["open", "closed", "all", "review"] = "open"):
    """Issue一覧

    reviewの場合は、状態に関わらずレビュー待ちMRを含むIssueを返す。
    """
    with SessionLocal() as session:
        project = session.get(Project, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")
        is_review = state == ISSUE_FILTER_REVIEW
        issues = list_issues(project.github_repo, "all" if is_review else state)
        counts = _mr_counts_by_issue(session, project.id)
        result = [{**i, "mr_counts": counts.get(i["number"], EMPTY_MR_COUNTS)} for i in issues]
        return [i for i in result if i["mr_counts"]["review"] > 0] if is_review else result


@router.get("/{project_id}/mr-counts")
def get_mr_counts(project_id: int):
    """画面の自動更新用にDB上のIssueごとのMR数を返す（GitHubへは問い合わせない）

    MRが無いIssueは含めない。
    """
    with SessionLocal() as session:
        project = _get_project_or_404(session, project_id)
        return _mr_counts_by_issue(session, project.id)


def _mr_counts_by_issue(session, project_id: int) -> dict[int, dict]:
    """Issueごとの解決済MR数・未解決MR数・MR総数・レビュー待ちMR数・デプロイ待ちMR数

    マージされずクローズされたMRはいずれにも数えない。
    未解決MR数は一覧の閉じるボタンの活性判定に使う。
    レビュー待ち・デプロイ待ちMR数はリポジトリ見出しの件数表示とレビューフィルタに使う。
    """
    rows = (
        session.query(
            Subtask.github_issue_number,
            _count_in(RESOLVED_LIFECYCLE_STATES),
            _count_in(UNRESOLVED_LIFECYCLE_STATES),
            func.count(),
            _count_in((REVIEW_LIFECYCLE_STATE,)),
            _count_in((UNDEPLOYED_LIFECYCLE_STATE,)),
        )
        .filter_by(project_id=project_id)
        .filter(Subtask.lifecycle_state != UNCOUNTED_LIFECYCLE_STATE)
        .group_by(Subtask.github_issue_number)
        .all()
    )
    return {
        number: {
            "resolved": resolved,
            "unresolved": unresolved,
            "total": total,
            "review": review,
            "undeployed": undeployed,
        }
        for number, resolved, unresolved, total, review, undeployed in rows
    }


def _count_in(states: tuple[str, ...]):
    return func.sum(case((Subtask.lifecycle_state.in_(states), 1), else_=0))


@router.post("/{project_id}/issues")
def create_project_issue(project_id: int, payload: CreateIssueRequest):
    """Issueを作成する

    続けて行うMR作成でIssue名を再取得せずに済むよう、作成したIssue名も返す。
    """
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="title is empty")
    with SessionLocal() as session:
        project = _get_project_or_404(session, project_id)
        try:
            issue = create_issue(project.github_repo, title, payload.body)
        except GitHubClientError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {**issue, "title": title}


class UpdateTitleRequest(BaseModel):
    title: str


@router.patch("/{project_id}/issues/{number}")
def update_issue_title(project_id: int, number: int, payload: UpdateTitleRequest):
    """Issue名を変更し、紐づくMR名のIssue名部分も書き換える

    命名規則に沿っていないMRは書き換えない。
    MRの書き換え失敗はIssue名変更を取り消さず、失敗一覧として返す。
    """
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="title is empty")
    with SessionLocal() as session:
        project = _get_project_or_404(session, project_id)
        try:
            old_title = get_issue(project.github_repo, number)["title"]
            edit_issue_title(project.github_repo, number, title)
        except GitHubClientError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        failed = _rename_subtasks(session, project, number, old_title, title)
        return {"number": number, "title": title, "failed_subtasks": failed}


def _rename_subtasks(session, project: Project, number: int, old_title: str, new_title: str):
    failed = []
    subtasks = session.query(Subtask).filter_by(project_id=project.id, github_issue_number=number)
    for subtask in subtasks:
        suffix = split_mr_title(old_title, subtask.title)
        if suffix is None:
            continue
        renamed = compose_mr_title(new_title, suffix)
        try:
            if subtask.github_pr_number is not None:
                edit_pr_title(project.github_repo, subtask.github_pr_number, renamed)
        except GitHubClientError as exc:
            failed.append({"id": subtask.id, "error": str(exc)})
            continue
        subtask.title = renamed
        session.commit()
    return failed


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


@router.post("/{project_id}/issues/{number}/close")
def close_project_issue(project_id: int, number: int):
    """Issueをクローズする

    未解決（Draft・Resolved）のMRが残っている場合は拒否する。
    """
    with SessionLocal() as session:
        project = _get_project_or_404(session, project_id)
        unresolved = (
            session.query(Subtask)
            .filter_by(project_id=project.id, github_issue_number=number)
            .filter(Subtask.lifecycle_state.in_(UNRESOLVED_LIFECYCLE_STATES))
            .count()
        )
        if unresolved:
            raise HTTPException(status_code=409, detail="未解決のMRが残っています")
        try:
            close_issue(project.github_repo, number)
        except GitHubClientError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"number": number, "state": "CLOSED"}


@router.post("/{project_id}/issues/{number}/reopen")
def reopen_project_issue(project_id: int, number: int):
    with SessionLocal() as session:
        project = _get_project_or_404(session, project_id)
        try:
            reopen_issue(project.github_repo, number)
        except GitHubClientError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"number": number, "state": "OPEN"}


@router.get("/{project_id}/issues/{number}/subtasks")
def get_issue_subtasks(project_id: int, number: int):
    """画面の自動更新用にDB上のサブタスク一覧を返す（GitHubへは問い合わせない）"""
    with SessionLocal() as session:
        project = _get_project_or_404(session, project_id)
        return _subtask_summaries(session, project, number)
