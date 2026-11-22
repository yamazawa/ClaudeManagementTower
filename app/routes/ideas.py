"""アイデアマンのAPI

アイデア出しジョブの投入、提案一覧の取得、却下を扱う。
承認（Issue・サブタスク作成）は後続のサブタスクで追加する。
"""

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.idea_queue import IdeaJobAlreadyActive, IdeaProjectNotFound, enqueue_idea_job, latest_idea_job
from core.ideas import IDEA_TABS, IdeaAlreadyDecided, IdeaNotFound, list_ideas, reject_idea

router = APIRouter(prefix="/api")


class RejectIdeaRequest(BaseModel):
    reason: str = ""


@router.post("/projects/{project_id}/ideas/run", status_code=202)
def run_idea_generation(project_id: int):
    """アイデア出しジョブを投入する

    結果は待たずに返し、画面は最新ジョブと提案一覧の取得で確認する。
    """
    try:
        return enqueue_idea_job(project_id)
    except IdeaProjectNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except IdeaJobAlreadyActive as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/projects/{project_id}/ideas")
def get_ideas(project_id: int, tab: Literal["pending", "approved", "rejected", "all"] = "pending"):
    return list_ideas(project_id, None if tab == "all" else IDEA_TABS[tab])


@router.get("/projects/{project_id}/idea-jobs/latest")
def get_latest_idea_job(project_id: int):
    return latest_idea_job(project_id)


@router.post("/ideas/{idea_id}/reject")
def post_reject_idea(idea_id: int, payload: RejectIdeaRequest):
    try:
        return reject_idea(idea_id, payload.reason)
    except IdeaNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except IdeaAlreadyDecided as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
