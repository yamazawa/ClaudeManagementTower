"""リポジトリ表示のCLI・Ideaタブの項目

CLIの対話（cli_sessions）とIdeaの項目（idea_sessions）で共通の、
タイトルとOpen・Closeの状態を扱う。
"""

from sqlalchemy.orm import sessionmaker

from core.db import SessionLocal
from core.models import Project

TITLE_MAX_LENGTH = 200


class ItemState:
    """項目のOpen・Closeの状態

    OPEN : 一覧のOpenに表示する
    CLOSED : 一覧のCloseに表示する
    """

    OPEN = "open"
    CLOSED = "closed"

    ALL = (OPEN, CLOSED)


class RepoItemNotFound(Exception):
    pass


class RepoItemInvalid(ValueError):
    pass


class RepoItemClosed(Exception):
    pass


def normalize_title(title: str) -> str:
    """前後の空白を除いたタイトル

    空のタイトルは受け付けない。
    """
    value = (title or "").strip()
    if not value:
        raise RepoItemInvalid("title is empty")
    if len(value) > TITLE_MAX_LENGTH:
        raise RepoItemInvalid("title is too long")
    return value


def ensure_project(session, project_id: int) -> None:
    if session.get(Project, project_id) is None:
        raise RepoItemNotFound("project not found")


def get_item_or_raise(session, model, item_id: int):
    item = session.get(model, item_id)
    if item is None:
        raise RepoItemNotFound(f"{model.__tablename__} not found")
    return item


def ensure_open(item) -> None:
    """Closeの項目では実行させない"""
    if item.state != ItemState.OPEN:
        raise RepoItemClosed("Closeの項目は実行できません")


def list_items(session, model, project_id: int, state: str):
    """指定状態の項目（新しい順）"""
    return (
        session.query(model)
        .filter(model.project_id == project_id, model.state == state)
        .order_by(model.id.desc())
        .all()
    )


def update_item(
    model,
    item_id: int,
    title: str | None = None,
    state: str | None = None,
    session_factory: sessionmaker = SessionLocal,
) -> int:
    """タイトル・状態を変更する

    指定の無い値は変更しない。
    """
    if state is not None and state not in ItemState.ALL:
        raise RepoItemInvalid("state is invalid")
    new_title = normalize_title(title) if title is not None else None
    with session_factory() as session:
        item = get_item_or_raise(session, model, item_id)
        if new_title is not None:
            item.title = new_title
        if state is not None:
            item.state = state
        session.commit()
        return item.id
