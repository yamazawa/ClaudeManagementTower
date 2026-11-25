from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import case, func

from app.routes import error_messages as messages
from app.routes.lookups import get_project_or_404
from core.db import SessionLocal
from core.deploy import is_deploy_defined, is_deploy_running
from core.github_client import (
    GitHubClientError,
    close_issue,
    edit_issue_title,
    edit_pr_title,
    get_issue,
    list_issues,
    list_issues_closed_since,
    reopen_issue,
)
from core.issue_mr_creation import EmptyTitleError, create_issue
from core.lifecycle import LifecycleState
from core.merge_queue import latest_merge_summary
from core.models import ExecutionJob, Project, Report, Subtask
from core.mr_naming import compose_mr_title, split_mr_title
from core.repo_catalog import describe_repo
from core.repo_setup import (
    RepoSetupError,
    RepoValidationError,
    create_repository,
    normalize_new_repo,
)

router = APIRouter(prefix="/api/projects")

# Issueクローズを妨げる未解決MRのlifecycle_state
UNRESOLVED_LIFECYCLE_STATES = LifecycleState.OPEN_STATES
# Issue一覧のMR数で解決済とみなすlifecycle_state
RESOLVED_LIFECYCLE_STATES = LifecycleState.MERGED_STATES
# Issue一覧のMR数から除外するlifecycle_state（マージされずクローズ）
UNCOUNTED_LIFECYCLE_STATE = LifecycleState.CANCELED
EMPTY_MR_COUNTS = {"resolved": 0, "unresolved": 0, "total": 0}
# Issue一覧で本日クローズされたIssueのみを返すステータス
ISSUE_STATE_CLOSED_TODAY = "closed_today"


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
    return {"id": job.id, "status": job.status, "has_report": has_report, "error_message": job.error_message}


class CreateIssueRequest(BaseModel):
    title: str
    body: str = ""


@router.get("")
def get_projects():
    with SessionLocal() as session:
        projects = session.query(Project).filter_by(removed=False).all()
        return [
            {
                "id": p.id,
                "name": p.name,
                "github_repo": p.github_repo,
                "default_branch": p.default_branch,
                "description": p.description,
                **describe_repo(p.github_repo, p.name, p.display_name),
                "deploy_defined": is_deploy_defined(p.repo_path),
            }
            for p in projects
        ]


class CreateProjectRequest(BaseModel):
    # 英語名（フォルダ名・GitHubのリポジトリ名）
    name: str
    # 日本語名（画面の表示名）
    display_name: str
    # 何をするPJか
    description: str


@router.post("")
def create_project(payload: CreateProjectRequest):
    """リポジトリを作成してリポジトリ一覧に追加する

    初期設定のIssue・MRのマージとIssueのクローズまで行う。
    登録後に初期設定で失敗した場合も、登録したリポジトリIDを返して画面で選択できるようにする。
    """
    try:
        repo = normalize_new_repo(payload.name, payload.display_name, payload.description)
        return create_repository(repo)
    except RepoValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RepoSetupError as exc:
        detail = {"message": str(exc), "project_id": exc.project_id}
        raise HTTPException(status_code=500, detail=detail) from exc


@router.delete("/{project_id}")
def remove_project(project_id: int):
    """リポジトリを一覧から削除する

    GitHub・ローカルのリポジトリと、MR等の履歴は削除しない。
    """
    with SessionLocal() as session:
        project = get_project_or_404(session, project_id)
        project.removed = True
        session.commit()
        return {"id": project_id, "removed": True}


@router.get("/{project_id}/issues")
def get_issues(project_id: int, state: Literal["open", "closed_today", "closed"] = "open"):
    """Issue一覧

    指定したステータスのIssueを返す。
    closed_todayは本日（サーバーのローカル時刻）クローズされたIssueのみを返す。
    """
    with SessionLocal() as session:
        project = get_project_or_404(session, project_id)
        issues = _list_issues_by_state(project.github_repo, state)
        counts = _mr_counts_by_issue(session, project.id)
        return [{**i, "mr_counts": counts.get(i["number"], EMPTY_MR_COUNTS)} for i in issues]


def _list_issues_by_state(repo: str, state: str) -> list[dict]:
    if state == ISSUE_STATE_CLOSED_TODAY:
        return list_issues_closed_since(repo, _start_of_today())
    return list_issues(repo, state)


def _start_of_today() -> datetime:
    """サーバーのローカル時刻での本日0時（タイムゾーン付き）"""
    now = datetime.now().astimezone()
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


@router.get("/{project_id}/mr-counts")
def get_mr_counts(project_id: int):
    """画面の自動更新用にDB上のIssueごとのMR数を返す（GitHubへは問い合わせない）

    MRが無いIssueは含めない。
    """
    with SessionLocal() as session:
        project = get_project_or_404(session, project_id)
        return _mr_counts_by_issue(session, project.id)


def _mr_counts_by_issue(session, project_id: int) -> dict[int, dict]:
    """Issueごとの解決済MR数・未解決MR数・MR総数

    マージされずクローズされたMRはいずれにも数えない。
    未解決MR数は一覧の閉じるボタンの活性判定に使う。
    """
    rows = (
        session.query(
            Subtask.github_issue_number,
            _count_in(RESOLVED_LIFECYCLE_STATES),
            _count_in(UNRESOLVED_LIFECYCLE_STATES),
            func.count(),
        )
        .filter_by(project_id=project_id)
        .filter(Subtask.lifecycle_state != UNCOUNTED_LIFECYCLE_STATE)
        .group_by(Subtask.github_issue_number)
        .all()
    )
    return {
        number: {"resolved": resolved, "unresolved": unresolved, "total": total}
        for number, resolved, unresolved, total in rows
    }


def _count_in(states: tuple[str, ...]):
    return func.sum(case((Subtask.lifecycle_state.in_(states), 1), else_=0))


@router.post("/{project_id}/issues")
def create_project_issue(project_id: int, payload: CreateIssueRequest):
    """Issueを作成する

    作成処理は画面・アイデアマン・CLIタブで共通の処理を使う。
    """
    with SessionLocal() as session:
        project = get_project_or_404(session, project_id)
    try:
        return create_issue(project, payload.title, payload.body)
    except EmptyTitleError as exc:
        raise HTTPException(status_code=400, detail=messages.TITLE_EMPTY) from exc
    except GitHubClientError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


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
        raise HTTPException(status_code=400, detail=messages.TITLE_EMPTY)
    with SessionLocal() as session:
        project = get_project_or_404(session, project_id)
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
    """IssueのMR一覧

    deployingは画面でDeployingを導出するため、リポジトリのデプロイ実行中かを返す。
    """
    subtasks = (
        session.query(Subtask)
        .filter_by(project_id=project.id, github_issue_number=number)
        .order_by(Subtask.id)
        .all()
    )
    deploying = is_deploy_running(project.id)
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
            "latest_merge": latest_merge_summary(session, s.id),
            "deploying": deploying,
        }
        for s in subtasks
    ]


@router.get("/{project_id}/issues/{number}")
def get_issue_detail(project_id: int, number: int):
    with SessionLocal() as session:
        project = get_project_or_404(session, project_id)
        issue = get_issue(project.github_repo, number)
        issue["subtasks"] = _subtask_summaries(session, project, number)
        return issue


@router.post("/{project_id}/issues/{number}/close")
def close_project_issue(project_id: int, number: int):
    """Issueをクローズする

    未解決（Draft・Resolved）のMRが残っている場合は拒否する。
    """
    with SessionLocal() as session:
        project = get_project_or_404(session, project_id)
        unresolved = (
            session.query(Subtask)
            .filter_by(project_id=project.id, github_issue_number=number)
            .filter(Subtask.lifecycle_state.in_(UNRESOLVED_LIFECYCLE_STATES))
            .count()
        )
        if unresolved:
            raise HTTPException(status_code=409, detail=messages.UNRESOLVED_MR_REMAINS)
        try:
            close_issue(project.github_repo, number)
        except GitHubClientError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"number": number, "state": "CLOSED"}


@router.post("/{project_id}/issues/{number}/reopen")
def reopen_project_issue(project_id: int, number: int):
    with SessionLocal() as session:
        project = get_project_or_404(session, project_id)
        try:
            reopen_issue(project.github_repo, number)
        except GitHubClientError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"number": number, "state": "OPEN"}


@router.get("/{project_id}/issues/{number}/subtasks")
def get_issue_subtasks(project_id: int, number: int):
    """画面の自動更新用にDB上のサブタスク一覧を返す（GitHubへは問い合わせない）"""
    with SessionLocal() as session:
        project = get_project_or_404(session, project_id)
        return _subtask_summaries(session, project, number)
