"""ルート共通のDB取得

プロジェクト・サブタスクを取得し、見つからない場合は404を送出する。
"""

from fastapi import HTTPException

from app.routes import error_messages as messages
from core.models import Project, Subtask


def get_project_or_404(session, project_id: int) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=messages.PROJECT_NOT_FOUND)
    return project


def get_subtask_or_404(session, subtask_id: int) -> Subtask:
    subtask = session.get(Subtask, subtask_id)
    if subtask is None:
        raise HTTPException(status_code=404, detail=messages.SUBTASK_NOT_FOUND)
    return subtask


def get_subtask_and_project_or_404(session, subtask_id: int) -> tuple[Subtask, Project]:
    """サブタスクと所属プロジェクトを取得する

    プロジェクトが削除済みの場合も404とする。
    """
    subtask = get_subtask_or_404(session, subtask_id)
    return subtask, get_project_or_404(session, subtask.project_id)
