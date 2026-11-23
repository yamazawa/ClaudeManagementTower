"""Claudeサブスクリプションの使用率取得

Claude Codeの/usageと同じOAuth使用率APIから5時間枠・1週間枠の使用率を取得する。
認証はClaude Codeがログイン時に保存したOAuthトークンを使い回す。
SDKのRateLimitEventは状態変化時しか通知されず使用率も欠けるため、こちらを主な取得元とする。
"""

import json
import os
import threading
import urllib.request
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from core.config import settings

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
OAUTH_BETA_HEADER = "oauth-2025-04-20"
USER_AGENT = "claude-tower"
REQUEST_TIMEOUT_SECONDS = 5

_cache: dict = {"usage": None, "attempted_at": None}


def credentials_path() -> Path:
    """OAuth認証情報ファイルのパスを返す

    設定値が空の場合はClaude Codeの既定の保存先を使う。
    """
    if settings.claude_credentials_path:
        return Path(settings.claude_credentials_path)
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude"
    return Path(config_dir) / ".credentials.json"


def read_access_token(path: Path | None = None) -> str | None:
    """保存済みのOAuthアクセストークンを読む

    ファイルが無い・形式が違う場合はNoneを返す。
    """
    try:
        data = json.loads((path or credentials_path()).read_text(encoding="utf-8"))
        return data["claudeAiOauth"]["accessToken"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def request_usage(token: str) -> dict:
    request = urllib.request.Request(
        USAGE_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "anthropic-beta": OAUTH_BETA_HEADER,
            "User-Agent": USER_AGENT,
        },
    )
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def _to_unix_seconds(iso_text: str | None) -> int | None:
    if not iso_text:
        return None
    try:
        return int(datetime.fromisoformat(iso_text.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def normalize_window(window: dict | None) -> dict | None:
    """使用率APIの枠1つ分をRateLimitEventと同じ形式に揃える

    使用率は百分率から0〜1の割合に、リセット時刻はUNIX秒に変換する。
    """
    if not isinstance(window, dict) or window.get("utilization") is None:
        return None
    return {
        "utilization": window["utilization"] / 100,
        "resets_at": _to_unix_seconds(window.get("resets_at")),
    }


def fetch_usage(
    token_reader: Callable[[], str | None] = read_access_token,
    requester: Callable[[str], dict] = request_usage,
) -> dict | None:
    """使用率APIの応答を取得する

    トークンが無い・通信に失敗した場合はNoneを返す。
    """
    token = token_reader()
    if not token:
        return None
    try:
        return requester(token)
    except Exception:
        return None


def refresh_usage(fetcher: Callable[[], dict | None] = fetch_usage) -> bool:
    """使用率APIを取得して保持値を更新する

    取得に失敗した場合は前回の取得値を残す。
    更新できたかを返す。
    """
    _cache["attempted_at"] = datetime.now(timezone.utc)
    usage = fetcher()
    if usage is None:
        return False
    _cache["usage"] = usage
    return True


def refresh_usage_if_older(since: datetime | None, fetcher: Callable[[], dict | None] = fetch_usage) -> bool:
    """指定時刻より後に取得を試みていなければ使用率APIを取得し直す

    上限到達などのレート制限通知を受けた直後に、使用率を通知に追従させるために使う。
    通知毎に1回だけ取得を試み、失敗しても画面のポーリング毎には再試行しない。
    """
    attempted_at = _cache["attempted_at"]
    if since is None or (attempted_at is not None and attempted_at >= since):
        return False
    return refresh_usage(fetcher)


def get_usage() -> dict | None:
    """保持している使用率APIの最新取得値を返す

    画面のポーリング毎にAPIは呼ばず、定期更新タスクの取得値を返す。
    """
    return _cache["usage"]


def clear_cache() -> None:
    _cache["usage"] = None
    _cache["attempted_at"] = None


def _refresh_loop(
    stop_event: threading.Event, interval_seconds: float, fetcher: Callable[[], dict | None]
) -> None:
    while not stop_event.is_set():
        try:
            refresh_usage(fetcher)
        except Exception as exc:  # noqa: BLE001
            # 一時的な失敗で定期更新を止めない
            print(f"[claude_usage] 使用率の取得に失敗しました: {exc}")
        stop_event.wait(interval_seconds)


def start_refresh_loop(
    interval_seconds: float, fetcher: Callable[[], dict | None] = fetch_usage
) -> threading.Event:
    """使用率の定期更新をバックグラウンドで開始する

    起動直後に1回取得し、以降は指定間隔で取得する。
    返したEventをsetすると停止する。
    """
    stop_event = threading.Event()
    thread = threading.Thread(
        target=_refresh_loop, args=(stop_event, interval_seconds, fetcher), daemon=True
    )
    thread.start()
    return stop_event
