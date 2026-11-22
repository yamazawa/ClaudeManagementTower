from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.cli_session import (
    CliSessionBusy,
    CliSessionNotFound,
    create_session,
    get_session,
    send_message,
)

router = APIRouter(prefix="/api/cli-sessions")


class CreateCliSessionRequest(BaseModel):
    project_id: int


class SendCliMessageRequest(BaseModel):
    text: str


@router.post("")
def create_cli_session(payload: CreateCliSessionRequest):
    try:
        return {"id": create_session(payload.project_id)}
    except CliSessionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{cli_session_id}/messages", status_code=202)
def post_cli_message(cli_session_id: int, payload: SendCliMessageRequest):
    """発言を受け付ける

    Claudeの応答は待たずに返し、画面は発言一覧の取得で応答を確認する。
    """
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is empty")
    try:
        send_message(cli_session_id, text)
    except CliSessionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CliSessionBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"accepted": True}


@router.get("/{cli_session_id}")
def get_cli_session(cli_session_id: int, after: int = 0):
    try:
        return get_session(cli_session_id, after_id=after)
    except CliSessionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
