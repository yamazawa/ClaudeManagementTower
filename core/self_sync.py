"""マージして最新化（Claude管理塔自身のPRをマージし、本体を最新化して再起動する）

競合解決でClaudeを起動するため、リクエスト処理とは別スレッドで実行する。
結果はサーバー再起動後も参照できるよう、制御ディレクトリにファイルで残す。
"""

import json
import threading
from collections.abc import Callable
from pathlib import Path

from core.config import settings
from core.git_client import GitClientError, pull_latest
from core.github_client import GitHubClientError, list_open_pull_requests
from core.pr_merger import PrMergeError, merge_pr_with_update
from core.pr_sync import mark_prs_merged
from core.supervisor_control import COMMAND_RESTART_SERVER, COMMAND_RESTART_WORKERS, request_command

STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"

RESULT_FILE_NAME = "sync-self-result.json"

_lock = threading.Lock()


class SelfSyncAlreadyRunning(RuntimeError):
    pass


def result_path() -> Path:
    return Path(settings.supervisor_control_dir) / RESULT_FILE_NAME


def read_result() -> dict | None:
    path = result_path()
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_result(result: dict) -> None:
    path = result_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")


def start_self_sync(repo_path: str, start_thread: Callable[[Callable[[], None]], None] | None = None) -> None:
    """マージして最新化を別スレッドで開始する（実行中なら例外）"""
    if not _lock.acquire(blocking=False):
        raise SelfSyncAlreadyRunning("マージして最新化は実行中です")
    _write_result({"status": STATUS_RUNNING})

    def run() -> None:
        try:
            run_self_sync(repo_path)
        except Exception as exc:
            # 想定外の例外でも結果を残し、画面が実行中のまま待ち続けないようにする
            _write_result({"status": STATUS_FAILED, "error": str(exc)})
        finally:
            _lock.release()

    (start_thread or _start_daemon_thread)(run)


def _start_daemon_thread(target: Callable[[], None]) -> None:
    threading.Thread(target=target, daemon=True).start()


def run_self_sync(repo_path: str) -> None:
    try:
        prs = [pr for pr in list_open_pull_requests(settings.self_repo) if not pr["isDraft"]]
        results = [_merge_one(repo_path, pr) for pr in prs]
        merged_pr_numbers = [r["number"] for r in results if r["error"] is None]
        mark_prs_merged(settings.self_repo, merged_pr_numbers)
        pull_latest(repo_path, "master")
    except (GitHubClientError, GitClientError) as exc:
        _write_result({"status": STATUS_FAILED, "error": str(exc)})
        return

    _write_result(
        {
            "status": STATUS_DONE,
            "merged_pr_numbers": merged_pr_numbers,
            "failed_prs": [r for r in results if r["error"] is not None],
        }
    )
    request_command(COMMAND_RESTART_SERVER)
    request_command(COMMAND_RESTART_WORKERS)


def _merge_one(repo_path: str, pr: dict) -> dict:
    """1件のPRをマージし、失敗しても他のPRの処理を続けられるよう結果で返す"""
    try:
        merge_pr_with_update(settings.self_repo, repo_path, settings.worktree_base_dir, pr)
    except (GitHubClientError, GitClientError, PrMergeError) as exc:
        return {"number": pr["number"], "error": str(exc)}
    return {"number": pr["number"], "error": None}
