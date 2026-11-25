"""CLIタブのAPI

CLIの項目（対話）の一覧・作成・変更と、発言の送信・取得・応答の中断を扱う。
応答中の許可の問い合わせへの回答も扱う。
発言に付ける添付ファイルの保存・取得・削除も扱う。
"""

from typing import Literal

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.routes import error_messages as messages
from app.routes.repo_items import RepoItemPatch, item_errors
from core.attachments import AttachmentError
from core.cli_attachments import delete_cli_attachment, find_cli_attachment_file, save_cli_attachment
from core.cli_permission_requests import PermissionRequestNotFound
from core.cli_session import (
    CliSessionBusy,
    CliSessionNotRunning,
    answer_permission,
    create_session,
    ensure_session_open,
    get_session,
    interrupt_turn,
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
    attachment_ids: list[str] = []


class AnswerCliPermissionRequest(BaseModel):
    allow: bool
    reason: str = ""


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
    添付ファイルは事前に保存したIDで指定する。
    """
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail=messages.TEXT_EMPTY)
    with item_errors():
        try:
            send_message(cli_session_id, text, payload.attachment_ids)
        except CliSessionBusy as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except AttachmentError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"accepted": True}


@router.post("/cli-sessions/{cli_session_id}/interrupt", status_code=202)
def post_cli_interrupt(cli_session_id: int):
    """応答中のClaudeを中断する

    中断の完了は待たずに返し、画面は発言一覧の取得で発言待ちに戻ったことを確認する。
    """
    with item_errors():
        try:
            interrupt_turn(cli_session_id)
        except CliSessionNotRunning as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"accepted": True}


@router.post("/cli-sessions/{cli_session_id}/permissions/{request_id}")
def post_cli_permission(cli_session_id: int, request_id: int, payload: AnswerCliPermissionRequest):
    """許可の問い合わせに回答する

    回答済み・中断済みの問い合わせは404とする。
    """
    try:
        answer_permission(cli_session_id, request_id, payload.allow, payload.reason)
    except PermissionRequestNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"accepted": True}


@router.get("/cli-sessions/{cli_session_id}")
def get_cli_session(cli_session_id: int, after: int = 0):
    with item_errors():
        return get_session(cli_session_id, after_id=after)


@router.post("/cli-sessions/{cli_session_id}/attachments")
async def upload_cli_attachment(cli_session_id: int, file: UploadFile):
    """発言の添付ファイルを保存する

    Closeの項目には添付できない。
    IDは項目内でS1、S2…の連番で割り当てる。
    """
    with item_errors():
        ensure_session_open(cli_session_id)
    try:
        return save_cli_attachment(cli_session_id, file.filename or "", await file.read())
    except AttachmentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/cli-sessions/{cli_session_id}/attachments/{attachment_id}/file")
def get_cli_attachment_file(cli_session_id: int, attachment_id: str):
    """添付ファイルの内容を返す

    発言一覧での表示に使う。
    """
    path = find_cli_attachment_file(cli_session_id, attachment_id)
    if path is None:
        raise HTTPException(status_code=404, detail=messages.ATTACHMENT_NOT_FOUND)
    return FileResponse(path)


@router.delete("/cli-sessions/{cli_session_id}/attachments/{attachment_id}")
def remove_cli_attachment(cli_session_id: int, attachment_id: str):
    """送信前の添付ファイルを取り消す

    残りの添付のIDは振り直さない。
    """
    if not delete_cli_attachment(cli_session_id, attachment_id):
        raise HTTPException(status_code=404, detail=messages.ATTACHMENT_NOT_FOUND)
    return {"id": attachment_id}
