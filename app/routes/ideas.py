"""アイデアマンのAPI

Ideaタブの項目の一覧・作成・変更、項目ごとのアイデア出しジョブの投入、
提案一覧の取得、承認・却下を扱う。
承認時のIssue・サブタスク作成は、画面・CLIタブと共通の作成処理を使う。
"""

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.routes import error_messages as messages
from app.routes.lookups import get_project_or_404
from app.routes.repo_items import RepoItemPatch, item_errors
from app.routes.subtasks import execute_subtask
from core.db import SessionLocal
from core.github_client import GitHubClientError
from core.idea_approval import (
    ApprovalMode,
    IdeaApprovalNotAllowed,
    claim_idea,
    compose_issue_body,
    compose_issue_title,
    compose_subtask_instruction,
    record_issue_created,
    record_subtask_created,
    release_claim,
    target_issue_number,
)
from core.idea_queue import IdeaJobAlreadyActive
from core.issue_mr_creation import CREATION_ERRORS, create_issue, create_issue_with_mr, create_mr
from core.idea_sessions import (
    create_session,
    get_session,
    list_session_ideas,
    list_sessions,
    run_session,
    update_session,
)
from core.ideas import IDEA_TABS, IdeaAlreadyDecided, IdeaNotFound, list_ideas, reject_idea
from core.models import Project
from core.repo_items import ItemState

router = APIRouter(prefix="/api")

# アイデアを出してほしい観点の最大文字数
IDEA_FOCUS_MAX_LENGTH = 1000


IdeaTab = Literal["pending", "approved", "rejected", "all"]


class CreateIdeaSessionRequest(BaseModel):
    project_id: int
    title: str


class RunIdeaRequest(BaseModel):
    # アイデアを出してほしい観点（空なら指定なし）
    focus: str = Field(default="", max_length=IDEA_FOCUS_MAX_LENGTH)


class RejectIdeaRequest(BaseModel):
    reason: str = ""


class ApproveIdeaRequest(BaseModel):
    mode: Literal["issue_only", "with_subtask"]
    # サブタスク作成後、そのまま実装の実行ジョブを投入するか
    execute: bool = True


def _tab_statuses(tab: str) -> tuple[str, ...] | None:
    return None if tab == "all" else IDEA_TABS[tab]


@router.get("/projects/{project_id}/idea-sessions")
def get_idea_sessions(project_id: int, state: Literal["open", "closed"] = ItemState.OPEN):
    return list_sessions(project_id, state)


@router.post("/idea-sessions")
def create_idea_session(payload: CreateIdeaSessionRequest):
    with item_errors():
        return create_session(payload.project_id, payload.title)


@router.get("/idea-sessions/{idea_session_id}")
def get_idea_session(idea_session_id: int):
    with item_errors():
        return get_session(idea_session_id)


@router.patch("/idea-sessions/{idea_session_id}")
def patch_idea_session(idea_session_id: int, payload: RepoItemPatch):
    with item_errors():
        return update_session(idea_session_id, payload.title, payload.state)


@router.post("/idea-sessions/{idea_session_id}/run", status_code=202)
def run_idea_generation(idea_session_id: int, payload: RunIdeaRequest | None = None):
    """項目のアイデア出しジョブを投入する

    結果は待たずに返し、画面は項目と提案一覧の取得で確認する。
    観点の指定は任意とする。
    """
    focus = payload.focus if payload else ""
    with item_errors():
        try:
            return run_session(idea_session_id, focus)
        except IdeaJobAlreadyActive as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/idea-sessions/{idea_session_id}/ideas")
def get_idea_session_ideas(idea_session_id: int, tab: IdeaTab = "pending"):
    with item_errors():
        return list_session_ideas(idea_session_id, _tab_statuses(tab))


@router.get("/projects/{project_id}/ideas")
def get_ideas(project_id: int, tab: IdeaTab = "pending"):
    return list_ideas(project_id, _tab_statuses(tab))


@router.post("/ideas/{idea_id}/reject")
def post_reject_idea(idea_id: int, payload: RejectIdeaRequest):
    try:
        return reject_idea(idea_id, payload.reason)
    except IdeaNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except IdeaAlreadyDecided as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _claim_or_raise(idea_id: int, mode: str) -> dict:
    try:
        return claim_idea(idea_id, mode)
    except IdeaNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (IdeaAlreadyDecided, IdeaApprovalNotAllowed) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _project_of(idea: dict) -> Project:
    with SessionLocal() as session:
        return get_project_or_404(session, idea["project_id"])


def _issue_failed(exc: Exception) -> HTTPException:
    return HTTPException(status_code=500, detail=messages.ISSUE_CREATE_FAILED.format(reason=exc))


def _subtask_failed(reason: object) -> HTTPException:
    return HTTPException(status_code=500, detail=messages.SUBTASK_CREATE_FAILED.format(reason=reason))


def _create_issue_only(idea: dict, project: Project) -> tuple[dict, str, None]:
    try:
        issue = create_issue(project, compose_issue_title(idea), compose_issue_body(idea))
    except GitHubClientError as exc:
        raise _issue_failed(exc) from exc
    return record_issue_created(idea["id"], issue["number"]), issue["url"], None


def _create_issue_with_mr(idea: dict, project: Project) -> tuple[dict, str, dict]:
    """提案からIssueとサブタスク（Draft PR）を作成する

    サブタスクのみ失敗した場合は、Issue作成済みを記録してから失敗とする。
    """
    try:
        created = create_issue_with_mr(
            project, compose_issue_title(idea), compose_issue_body(idea), compose_subtask_instruction(idea)
        )
    except GitHubClientError as exc:
        raise _issue_failed(exc) from exc
    idea = record_issue_created(idea["id"], created["issue"]["number"])
    if created["mr"] is None:
        raise _subtask_failed(created["mr_error"])
    return record_subtask_created(idea["id"], created["mr"]["id"]), created["issue"]["url"], created["mr"]


def _create_mr_for_issue(idea: dict, project: Project) -> tuple[dict, None, dict]:
    """既存Issue配下（またはIssue作成済み）の提案にサブタスク（Draft PR）を作成する

    作成失敗後の再作成でもブランチ名を重複させないよう、一意な識別子を使う。
    """
    try:
        mr = create_mr(
            project,
            target_issue_number(idea),
            instruction=compose_subtask_instruction(idea),
            unique_branch=True,
        )
    except CREATION_ERRORS as exc:
        raise _subtask_failed(exc) from exc
    return record_subtask_created(idea["id"], mr["id"]), None, mr


def _create_for_claimed(idea: dict, mode: str) -> tuple[dict, str | None, dict | None]:
    """承認処理中の提案に、Issue・サブタスクを共通の作成処理で作成する"""
    project = _project_of(idea)
    if target_issue_number(idea) is not None:
        return _create_mr_for_issue(idea, project)
    if mode == ApprovalMode.ISSUE_ONLY:
        return _create_issue_only(idea, project)
    return _create_issue_with_mr(idea, project)


@router.post("/ideas/{idea_id}/approve")
def post_approve_idea(idea_id: int, payload: ApproveIdeaRequest):
    """提案を承認し、Issue（とサブタスク）を作成する

    既存Issue配下の提案は、Issueを作らずサブタスクのみ作成する。
    作成処理は画面・CLIタブと共通の処理を使う。
    失敗した場合は承認前の状態へ戻す（Issue作成済みならIssue作成済みに戻す）。
    サブタスクも作成する場合、指定があれば作成後に実装の実行ジョブを投入する。
    """
    idea = _claim_or_raise(idea_id, payload.mode)
    try:
        idea, issue_url, subtask = _create_for_claimed(idea, payload.mode)
    except Exception:
        release_claim(idea["id"])
        raise
    if subtask is not None:
        subtask = {**subtask, "job": execute_subtask(subtask["id"]) if payload.execute else None}
    return {"idea": idea, "issue_url": issue_url, "subtask": subtask}
