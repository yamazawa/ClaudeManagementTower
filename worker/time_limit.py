"""Claude実行の最大実行時間の制御"""

import asyncio
from collections.abc import Coroutine
from typing import TypeVar

T = TypeVar("T")

TIMEOUT_MESSAGE_FORMAT = "Claudeの実行が最大実行時間（{seconds}秒）を超えたため打ち切りました"


class ClaudeTimeoutError(Exception):
    """Claudeの実行が最大実行時間を超えた"""


def run_with_time_limit(coro: Coroutine[object, object, T], timeout_seconds: float) -> T:
    """コルーチンを最大実行時間付きで実行する

    上限を超えた場合はコルーチンをキャンセルし、ClaudeTimeoutErrorを送出する。
    """
    try:
        return asyncio.run(asyncio.wait_for(coro, timeout_seconds))
    except asyncio.TimeoutError as exc:
        raise ClaudeTimeoutError(TIMEOUT_MESSAGE_FORMAT.format(seconds=timeout_seconds)) from exc
