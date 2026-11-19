"""Claudeサブスクリプションの使用率取得

Claude Codeの/usageと同じOAuth使用率APIから5時間枠・1週間枠の使用率を取得する。
認証はClaude Codeがログイン時に保存したOAuthトークンを使い回す。
SDKのRateLimitEventは状態変化時しか通知されず使用率も欠けるため、こちらを主な取得元とする。
"""

import json
import os
import time
import urllib.request
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from core.config import settings

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
OAUTH_BETA_HEADER = "oauth-2025-04-20"
USER_AGENT = "claude-tower"
REQUEST_TIMEOUT_SECONDS = 5

_cache: dict = {"fetched_at": None, "usage": None}


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


def get_usage(fetcher: Callable[[], dict | None] = fetch_usage, now: Callable[[], float] = time.monotonic) -> dict | None:
    """使用率APIの応答をキャッシュ付きで返す

    画面のポーリング毎にAPIを呼ばないよう、失敗時も含めて一定時間キャッシュする。
    """
    fetched_at = _cache["fetched_at"]
    if fetched_at is not None and now() - fetched_at < settings.claude_usage_cache_seconds:
        return _cache["usage"]
    _cache["usage"] = fetcher()
    _cache["fetched_at"] = now()
    return _cache["usage"]


def clear_cache() -> None:
    _cache["fetched_at"] = None
    _cache["usage"] = None
