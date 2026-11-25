"""CLIタブの許可問い合わせ

開発PCのCLIのように、範囲外の操作を実行前に利用者へ確認する。
問い合わせはClaude実行のスレッドで待機し、画面からの回答をAPIのスレッドから受け取る。
問い合わせはメモリ上にのみ保持し、サーバー再起動時は破棄する（応答の中断として扱う）。
"""

import asyncio
import itertools
import threading

PERMISSION_DENIED_MESSAGE = "利用者が操作を拒否しました。"
PERMISSION_DENIED_WITH_REASON_MESSAGE = "利用者が操作を拒否しました。理由: {reason}"


class PermissionRequestNotFound(Exception):
    pass


class _PermissionRequest:
    """回答待ちの1件の問い合わせ

    回答は待機中のイベントループへスレッドをまたいで渡す。
    """

    def __init__(self, request_id: int, tool: str, reason: str) -> None:
        self.id = request_id
        self.tool = tool
        self.reason = reason
        self._loop = asyncio.get_running_loop()
        self.future: asyncio.Future = self._loop.create_future()

    def to_dict(self) -> dict:
        return {"id": self.id, "tool": self.tool, "reason": self.reason}

    def resolve(self, denial: str | None) -> None:
        self._call_threadsafe(lambda: self.future.done() or self.future.set_result(denial))

    def cancel(self) -> None:
        self._call_threadsafe(self.future.cancel)

    def _call_threadsafe(self, callback) -> None:
        try:
            self._loop.call_soon_threadsafe(callback)
        except RuntimeError:
            pass  # 応答が終わりイベントループが閉じている


# 回答待ちの問い合わせ（対話のID → 問い合わせのID → 問い合わせ）
_requests: dict[int, dict[int, _PermissionRequest]] = {}
_requests_lock = threading.Lock()
_request_ids = itertools.count(1)


def _register(cli_session_id: int, tool: str, reason: str) -> _PermissionRequest:
    with _requests_lock:
        request = _PermissionRequest(next(_request_ids), tool, reason)
        _requests.setdefault(cli_session_id, {})[request.id] = request
        return request


def _unregister(cli_session_id: int, request_id: int) -> None:
    with _requests_lock:
        _requests.get(cli_session_id, {}).pop(request_id, None)


async def ask(cli_session_id: int, tool: str, reason: str) -> str | None:
    """利用者に許可を問い合わせ、回答を待つ

    許可ならNone、拒否ならClaudeに伝える理由を返す。
    """
    request = _register(cli_session_id, tool, reason)
    try:
        return await request.future
    finally:
        _unregister(cli_session_id, request.id)


def denial_message(reason: str) -> str:
    reason = reason.strip()
    return PERMISSION_DENIED_WITH_REASON_MESSAGE.format(reason=reason) if reason else PERMISSION_DENIED_MESSAGE


def answer(cli_session_id: int, request_id: int, allow: bool, reason: str = "") -> None:
    """問い合わせに回答する

    回答済み・存在しない問い合わせはPermissionRequestNotFoundとする。
    """
    with _requests_lock:
        request = _requests.get(cli_session_id, {}).pop(request_id, None)
    if request is None:
        raise PermissionRequestNotFound("許可の問い合わせが見つかりません（回答済み・中断済みの可能性があります）")
    request.resolve(None if allow else denial_message(reason))


def list_requests(cli_session_id: int) -> list[dict]:
    """回答待ちの問い合わせ（古い順）"""
    with _requests_lock:
        return [request.to_dict() for request in _requests.get(cli_session_id, {}).values()]


def discard(cli_session_id: int) -> None:
    """対話の回答待ちの問い合わせを全て取り消す

    応答の中断・終了時に、待機中の実行を止めるために使う。
    """
    with _requests_lock:
        requests = list(_requests.pop(cli_session_id, {}).values())
    for request in requests:
        request.cancel()
