import time
from collections.abc import Callable, Iterable
from typing import TypeVar

T = TypeVar("T")


class TransientError(RuntimeError):
    """再試行で回復が見込める一時的な通信エラー"""


def contains_any_pattern(text: str, patterns: Iterable[str]) -> bool:
    """textに判定文字列のいずれかが含まれるか

    大文字小文字を区別しない。
    判定文字列は小文字で定義する。
    """
    lowered = text.lower()
    return any(pattern in lowered for pattern in patterns)


def call_with_retry(
    operation: Callable[[], T],
    max_attempts: int,
    interval_seconds: float,
    retry_on: type[Exception] = TransientError,
) -> T:
    """operationを実行し、retry_onの例外なら間隔を空けて再試行する

    待ち時間は試行ごとにinterval_seconds分ずつ伸ばす。
    最大試行回数に達した場合、最後の例外をそのまま投げる。
    """
    for attempt in range(1, max_attempts + 1):
        try:
            return operation()
        except retry_on:
            if attempt == max_attempts:
                raise
            time.sleep(interval_seconds * attempt)
    raise AssertionError("unreachable")
