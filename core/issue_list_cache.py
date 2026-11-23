import threading
import time
from typing import Callable

# キャッシュのキー（リポジトリ, 一覧の種類）
CacheKey = tuple[str, str]


class IssueListCache:
    """Issue一覧の取得結果を短時間保持するキャッシュ

    キーは(リポジトリ, 一覧の種類)とし、保持時間を過ぎたら再取得する。
    保持時間が0以下の場合はキャッシュせず、毎回取得する。
    取得に失敗した場合は何も保持しない。
    """

    def __init__(self, ttl_seconds: Callable[[], float], clock: Callable[[], float] = time.monotonic):
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._entries: dict[CacheKey, tuple[float, list[dict]]] = {}
        self._lock = threading.Lock()

    def get_or_load(self, key: CacheKey, loader: Callable[[], list[dict]]) -> list[dict]:
        ttl = self._ttl_seconds()
        if ttl <= 0:
            return loader()
        cached = self._get_fresh(key, ttl)
        if cached is not None:
            return _copy(cached)
        issues = loader()
        with self._lock:
            self._entries[key] = (self._clock(), issues)
        return _copy(issues)

    def _get_fresh(self, key: CacheKey, ttl: float) -> list[dict] | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            stored_at, issues = entry
            if self._clock() - stored_at >= ttl:
                del self._entries[key]
                return None
            return issues

    def invalidate_repo(self, repo: str) -> None:
        """指定リポジトリの全種類の一覧を破棄する"""
        with self._lock:
            for key in [k for k in self._entries if k[0] == repo]:
                del self._entries[key]

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


def _copy(issues: list[dict]) -> list[dict]:
    """呼び出し側の変更がキャッシュに及ばないよう、要素ごとに複製する"""
    return [dict(issue) for issue in issues]
