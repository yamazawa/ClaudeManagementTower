"""アイデアマンのAPI

Ideaタブの項目の一覧・作成・変更、項目ごとのアイデア出しジョブの投入、
提案一覧の取得、承認・却下を扱う。
承認時のIssue・サブタスク作成は、既存のIssue作成・MR作成・実装実行の処理を使う。
"""

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.routes.lookups import get_project_or_404
from app.routes.repo_items import RepoItemPatch, item_errors
from app.routes.subtasks import CreateSubtaskRequest, create_subtask, execute_subtask
from core.db import SessionLocal
from core.github_client import GitHubClientError, create_issue
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
from core.idea_sessions import (
    create_session,
    get_session,
    list_session_ideas,
    list_sessions,
    run_session,
    update_session,
)
from core.ideas import IDEA_TABS, IdeaAlreadyDecided, IdeaNotFound, list_ideas, reject_idea
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


def _github_repo(project_id: int) -> str:
    with SessionLocal() as session:
        return get_project_or_404(session, project_id).github_repo


def _create_issue_for(idea: dict) -> tuple[dict, str, str]:
    """提案からIssueを作成する

    作成に失敗した場合は承認前の状態へ戻す。
    """
    title = compose_issue_title(idea)
    try:
        issue = create_issue(_github_repo(idea["project_id"]), title, compose_issue_body(idea))
    except GitHubClientError as exc:
        release_claim(idea["id"])
        raise HTTPException(status_code=500, detail=f"Issue作成に失敗しました: {exc}") from exc
    return record_issue_created(idea["id"], issue["number"]), issue["url"], title


def _create_subtask_for(idea: dict, issue_title: str, execute: bool) -> tuple[dict, dict]:
    """提案のIssue配下にサブタスク（Draft PR）を作成し、指定があれば実装を開始する

    作成に失敗した場合は承認前の状態へ戻す（Issue作成済みならIssue作成済みに戻す）。
    """
    payload = CreateSubtaskRequest(
        project_id=idea["project_id"],
        github_issue_number=target_issue_number(idea),
        instruction=compose_subtask_instruction(idea),
        issue_title=issue_title,
        unique_branch=True,
    )
    try:
        subtask = create_subtask(payload)
    except HTTPException as exc:
        release_claim(idea["id"])
        raise HTTPException(status_code=exc.status_code, detail=f"サブタスク作成に失敗しました: {exc.detail}") from exc
    idea = record_subtask_created(idea["id"], subtask["id"])
    return idea, {**subtask, "job": execute_subtask(subtask["id"]) if execute else None}


@router.post("/ideas/{idea_id}/approve")
def post_approve_idea(idea_id: int, payload: ApproveIdeaRequest):
    """提案を承認し、Issue（とサブタスク）を作成する

    既存Issue配下の提案は、Issueを作らずサブタスクのみ作成する。
    サブタスクも作成する場合、指定があれば作成後に実装の実行ジョブを投入する。
    """
    idea = _claim_or_raise(idea_id, payload.mode)
    issue_url, issue_title, subtask = None, "", None
    if target_issue_number(idea) is None:
        idea, issue_url, issue_title = _create_issue_for(idea)
    if payload.mode == ApprovalMode.WITH_SUBTASK:
        idea, subtask = _create_subtask_for(idea, issue_title, payload.execute)
    return {"idea": idea, "issue_url": issue_url, "subtask": subtask}
