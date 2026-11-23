"""CLI・Ideaタブの項目のAPIで共通の定義"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel

from core.repo_items import RepoItemClosed, RepoItemInvalid, RepoItemNotFound


class RepoItemPatch(BaseModel):
    """項目のタイトル・Open・Closeの変更（指定の無い値は変更しない）"""

    title: str | None = None
    state: Literal["open", "closed"] | None = None


@contextmanager
def item_errors() -> Iterator[None]:
    """項目の操作で起きた例外をHTTPのエラーに変換する"""
    try:
        yield
    except RepoItemNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RepoItemInvalid as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RepoItemClosed as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
