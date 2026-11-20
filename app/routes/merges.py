from fastapi import APIRouter

from core.db import SessionLocal
from core.merge_queue import list_active_merges

router = APIRouter(prefix="/api/merges")


@router.get("")
def get_merges():
    """マージ中・マージ待ちのMRを処理順に返す"""
    with SessionLocal() as session:
        return list_active_merges(session)
