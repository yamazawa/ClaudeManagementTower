"""CLIタブのAPI

CLIの項目（対話）の一覧・作成・変更と、発言の送信・取得を扱う。
"""

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.routes.repo_items import RepoItemPatch, item_errors
from core.cli_session import (
    CliSessionBusy,
    create_session,
    get_session,
    list_sessions,
    send_message,
    update_session,
)
from core.repo_items import ItemState

router = APIRouter(prefix="/api")


class CreateCliSessionRequest(BaseModel):
    project_id: int
    title: str


class SendCliMessageRequest(BaseModel):
    text: str


@router.get("/projects/{project_id}/cli-sessions")
def get_cli_sessions(project_id: int, state: Literal["open", "closed"] = ItemState.OPEN):
    return list_sessions(project_id, state)


@router.post("/cli-sessions")
def create_cli_session(payload: CreateCliSessionRequest):
    with item_errors():
        return create_session(payload.project_id, payload.title)


@router.patch("/cli-sessions/{cli_session_id}")
def patch_cli_session(cli_session_id: int, payload: RepoItemPatch):
    with item_errors():
        return update_session(cli_session_id, payload.title, payload.state)


@router.post("/cli-sessions/{cli_session_id}/messages", status_code=202)
def post_cli_message(cli_session_id: int, payload: SendCliMessageRequest):
    """発言を受け付ける

    Claudeの応答は待たずに返し、画面は発言一覧の取得で応答を確認する。
    """
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is empty")
    with item_errors():
        try:
            send_message(cli_session_id, text)
        except CliSessionBusy as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"accepted": True}


@router.get("/cli-sessions/{cli_session_id}")
def get_cli_session(cli_session_id: int, after: int = 0):
    with item_errors():
        return get_session(cli_session_id, after_id=after)
