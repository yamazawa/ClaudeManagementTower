"""Ideaタブの項目（idea_sessions）

項目ごとにアイデア出しを実行し、その提案を確認する。
項目はリポジトリの項目として、タイトルとOpen・Closeの状態を持つ。
"""

from sqlalchemy.orm import sessionmaker

from core.db import SessionLocal
from core.idea_queue import enqueue_idea_job, latest_session_jobs
from core.ideas import list_ideas
from core.models import IdeaSession
from core.repo_items import (
    ItemState,
    ensure_open,
    ensure_project,
    get_item_or_raise,
    list_items,
    normalize_title,
    update_item,
)


def session_to_dict(idea_session: IdeaSession, latest_job: dict | None) -> dict:
    return {
        "id": idea_session.id,
        "project_id": idea_session.project_id,
        "title": idea_session.title,
        "state": idea_session.state,
        "created_at": idea_session.created_at,
        "updated_at": idea_session.updated_at,
        "latest_job": latest_job,
    }


def _with_latest_jobs(session, idea_sessions: list[IdeaSession]) -> list[dict]:
    jobs = latest_session_jobs(session, [s.id for s in idea_sessions])
    return [session_to_dict(s, jobs.get(s.id)) for s in idea_sessions]


def list_sessions(project_id: int, state: str, session_factory: sessionmaker = SessionLocal) -> list[dict]:
    """Idea一覧（新しい順・最新のアイデア出しジョブ付き）"""
    with session_factory() as session:
        return _with_latest_jobs(session, list_items(session, IdeaSession, project_id, state))


def get_session(idea_session_id: int, session_factory: sessionmaker = SessionLocal) -> dict:
    with session_factory() as session:
        idea_session = get_item_or_raise(session, IdeaSession, idea_session_id)
        return _with_latest_jobs(session, [idea_session])[0]


def create_session(project_id: int, title: str, session_factory: sessionmaker = SessionLocal) -> dict:
    """Ideaの項目をOpenで作成する"""
    value = normalize_title(title)
    with session_factory() as session:
        ensure_project(session, project_id)
        idea_session = IdeaSession(project_id=project_id, title=value, state=ItemState.OPEN)
        session.add(idea_session)
        session.commit()
        return session_to_dict(idea_session, None)


def update_session(
    idea_session_id: int,
    title: str | None = None,
    state: str | None = None,
    session_factory: sessionmaker = SessionLocal,
) -> dict:
    """タイトル・Open・Closeを変更する"""
    update_item(IdeaSession, idea_session_id, title, state, session_factory)
    return get_session(idea_session_id, session_factory)


def run_session(idea_session_id: int, focus: str, session_factory: sessionmaker = SessionLocal) -> dict:
    """項目のアイデア出しジョブを投入する

    Closeの項目では実行しない。
    """
    with session_factory() as session:
        idea_session = get_item_or_raise(session, IdeaSession, idea_session_id)
        ensure_open(idea_session)
        project_id = idea_session.project_id
    return enqueue_idea_job(project_id, focus, session_factory, idea_session_id=idea_session_id)


def list_session_ideas(
    idea_session_id: int,
    statuses: tuple[str, ...] | None,
    session_factory: sessionmaker = SessionLocal,
) -> list[dict]:
    """項目で実行したアイデア出しの提案一覧（新しい順）"""
    with session_factory() as session:
        project_id = get_item_or_raise(session, IdeaSession, idea_session_id).project_id
    return list_ideas(project_id, statuses, session_factory, idea_session_id=idea_session_id)
