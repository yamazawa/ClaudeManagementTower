"""Claudeのレート制限状況の記録・取得

Claude Agent SDKが通知するRateLimitEventを枠ごとに保存する。
画面のヘッダーに5時間枠・1週間枠の使用率を表示するために使う。
使用率は使用率APIの値を優先し、SDK通知の値は補助として使う。
"""

import re
from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy.orm import sessionmaker

from core.claude_usage import get_usage, normalize_window
from core.db import SessionLocal
from core.models import RateLimitSnapshot

# 画面に表示する枠（SDKのRateLimitTypeの値）
FIVE_HOUR = "five_hour"
SEVEN_DAY = "seven_day"
# 画面に表示する枠と枠の長さ（秒）
DISPLAY_WINDOW_SECONDS = {FIVE_HOUR: 5 * 60 * 60, SEVEN_DAY: 7 * 24 * 60 * 60}

# 上限に達している状態（SDKのRateLimitStatusの値）
STATUS_REJECTED = "rejected"
# 上限に達しているとみなす使用率（0〜1の割合）
FULL_UTILIZATION = 1.0

# 利用上限で失敗したとみなすClaudeのエラーメッセージ
RATE_LIMIT_ERROR_PATTERN = re.compile(r"hit your .*limit|usage limit reached", re.IGNORECASE)


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


def is_rate_limit_error(message: str) -> bool:
    return bool(RATE_LIMIT_ERROR_PATTERN.search(message or ""))


def blocked_until(session_factory: sessionmaker = SessionLocal) -> int | None:
    """上限中の枠のうち、最も遅いリセット時刻を返す

    全ての枠を対象とし、上限中でリセット時刻が未来の枠が無ければNoneを返す。
    リセット時刻が不明な上限は、待機し続けないよう対象外とする。
    """
    now = datetime.now(timezone.utc).timestamp()
    with session_factory() as session:
        snapshots = session.query(RateLimitSnapshot).filter(RateLimitSnapshot.status == STATUS_REJECTED).all()
        resets = [_future_resets_at(s.resets_at, now) for s in snapshots]
    return max((r for r in resets if r is not None), default=None)


def _to_dict(snapshot: RateLimitSnapshot | None) -> dict | None:
    if snapshot is None:
        return None
    return {
        "status": snapshot.status,
        "utilization": snapshot.utilization,
        "resets_at": snapshot.resets_at,
        "updated_at": snapshot.updated_at,
    }


def _future_resets_at(resets_at: int | None, now: float) -> int | None:
    """リセット時刻が未来の場合のみ返す

    過ぎたリセット時刻は前の枠の値のため表示しない。
    """
    return resets_at if resets_at is not None and resets_at > now else None


def _to_timestamp(value: datetime) -> float:
    """日時をUNIX秒に変換する

    SQLiteから読んだタイムゾーン無しの日時はUTCとみなす。
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()


def _is_current_status(snapshot: dict, usage_window: dict | None, window_seconds: int, now: float) -> bool:
    """SDK通知の状態が現在の枠のものかを判定する

    リセット時刻があれば、それが未来の場合のみ現在の枠とする。
    リセット時刻が無ければ、受信時刻が現在の枠の開始以降かで判定する。
    使用率APIにリセット時刻が無い場合は、枠が始まっていないとみなす。
    """
    if snapshot["resets_at"] is not None:
        return snapshot["resets_at"] > now
    if usage_window is not None and usage_window["resets_at"] is None:
        return False
    window_end = usage_window["resets_at"] if usage_window is not None else now
    return _to_timestamp(snapshot["updated_at"]) >= window_end - window_seconds


def _current_snapshot(snapshot: dict | None, usage_window: dict | None, window_seconds: int, now: float) -> dict | None:
    """SDK通知の状況から前の枠の状態・リセット時刻を除く"""
    if snapshot is None:
        return None
    current = _is_current_status(snapshot, usage_window, window_seconds, now)
    return {
        **snapshot,
        "status": snapshot["status"] if current else None,
        "resets_at": _future_resets_at(snapshot["resets_at"], now),
    }


def _merge_usage(snapshot: dict | None, usage_window: dict | None, window_seconds: int, now: float) -> dict | None:
    """SDK通知の状況に使用率APIの値を重ねる

    使用率・リセット時刻は使用率APIを優先し、状態は現在の枠のSDK通知の値を使う。
    使用率APIにリセット時刻が無い場合は、SDK通知の未来のリセット時刻で補う。
    使用率APIで上限に達している場合は、SDK通知を待たず上限中の状態とする。
    """
    snapshot = _current_snapshot(snapshot, usage_window, window_seconds, now)
    if usage_window is None:
        return snapshot
    merged = {**(snapshot or {"status": None, "updated_at": None, "resets_at": None}), **usage_window}
    if usage_window["resets_at"] is None:
        merged["resets_at"] = snapshot["resets_at"] if snapshot else None
    if usage_window["utilization"] >= FULL_UTILIZATION:
        merged["status"] = STATUS_REJECTED
    return merged


def get_rate_limits(
    session_factory: sessionmaker = SessionLocal,
    usage_getter: Callable[[], dict | None] = get_usage,
) -> dict:
    """画面表示する枠の最新状況を返す

    どちらの取得元にも無い枠はNoneとする。
    """
    usage = usage_getter() or {}
    now = datetime.now(timezone.utc).timestamp()
    with session_factory() as session:
        return {
            rate_limit_type: _merge_usage(
                _to_dict(session.get(RateLimitSnapshot, rate_limit_type)),
                normalize_window(usage.get(rate_limit_type)),
                window_seconds,
                now,
            )
            for rate_limit_type, window_seconds in DISPLAY_WINDOW_SECONDS.items()
        }
