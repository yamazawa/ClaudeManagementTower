"""Claudeのレート制限状況の記録・取得

Claude Agent SDKが通知するRateLimitEventを枠ごとに保存する。
画面のヘッダーに5時間枠・1週間枠の使用率を表示するために使う。
使用率は使用率APIの値を優先し、SDK通知の値は補助として使う。
"""

from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy.orm import sessionmaker

from core.claude_usage import get_usage, normalize_window
from core.db import SessionLocal
from core.models import RateLimitSnapshot

# 画面に表示する枠（SDKのRateLimitTypeの値）
FIVE_HOUR = "five_hour"
SEVEN_DAY = "seven_day"
DISPLAY_TYPES = (FIVE_HOUR, SEVEN_DAY)


def record_rate_limit(info: object, session_factory: sessionmaker = SessionLocal) -> bool:
    """レート制限情報を保存する

    枠の種類が無い情報は保存しない。
    同じ枠の既存行は上書きする。
    """
    rate_limit_type = getattr(info, "rate_limit_type", None)
    if not rate_limit_type:
        return False
    with session_factory() as session:
        snapshot = session.get(RateLimitSnapshot, rate_limit_type)
        if snapshot is None:
            snapshot = RateLimitSnapshot(rate_limit_type=rate_limit_type)
            session.add(snapshot)
        snapshot.status = info.status
        snapshot.utilization = info.utilization
        snapshot.resets_at = info.resets_at
        snapshot.updated_at = datetime.now(timezone.utc)
        session.commit()
    return True


def _to_dict(snapshot: RateLimitSnapshot | None) -> dict | None:
    if snapshot is None:
        return None
    return {
        "status": snapshot.status,
        "utilization": snapshot.utilization,
        "resets_at": snapshot.resets_at,
        "updated_at": snapshot.updated_at,
    }


def _merge_usage(snapshot: dict | None, usage_window: dict | None) -> dict | None:
    """SDK通知の状況に使用率APIの値を重ねる

    使用率・リセット時刻は使用率APIを優先し、状態はSDK通知の値を使う。
    """
    if usage_window is None:
        return snapshot
    return {**(snapshot or {"status": None, "updated_at": None}), **usage_window}


def get_rate_limits(
    session_factory: sessionmaker = SessionLocal,
    usage_getter: Callable[[], dict | None] = get_usage,
) -> dict:
    """画面表示する枠の最新状況を返す

    どちらの取得元にも無い枠はNoneとする。
    """
    usage = usage_getter() or {}
    with session_factory() as session:
        return {
            rate_limit_type: _merge_usage(
                _to_dict(session.get(RateLimitSnapshot, rate_limit_type)),
                normalize_window(usage.get(rate_limit_type)),
            )
            for rate_limit_type in DISPLAY_TYPES
        }
