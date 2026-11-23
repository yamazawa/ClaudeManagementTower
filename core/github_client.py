import json
import logging
import subprocess
import time
from datetime import datetime

from core.config import settings
from core.issue_list_cache import IssueListCache

logger = logging.getLogger(__name__)

GH_TIMEOUT_SECONDS = 60
ISSUE_LIST_LIMIT = 200
PR_STATE_LIST_LIMIT = 200
# PR状態の同期と、管理塔外で作成されたPRの取り込みに使う項目
PR_STATE_FIELDS = "number,isDraft,state,mergedAt,title,headRefName,closingIssuesReferences"
# 一時的な通信エラー時の再試行（初回を含む最大試行回数と、試行ごとに伸ばす待ち時間）
GH_MAX_ATTEMPTS = 3
GH_RETRY_INTERVAL_SECONDS = 3
# stderrにこれらが含まれる場合は一時的な通信エラーとみなす（小文字で比較）
GH_TRANSIENT_ERROR_PATTERNS = (
    "tls handshake timeout",
    "connection reset",
    "connection refused",
    "i/o timeout",
    "timeout awaiting response headers",
    "unexpected eof",
    "http 502",
    "http 503",
    "http 504",
    "502 bad gateway",
    "503 service unavailable",
    "504 gateway timeout",
)
# closed_sinceのキャッシュキーの接頭辞（後ろに起点日時を付ける）
CLOSED_SINCE_CACHE_KIND = "closed_since:"

_issue_list_cache = IssueListCache(lambda: settings.issue_list_cache_ttl_seconds)


class GitHubClientError(RuntimeError):
    pass


class _TransientGhError(GitHubClientError):
    pass


def is_transient_gh_error(stderr: str) -> bool:
    lowered = stderr.lower()
    return any(pattern in lowered for pattern in GH_TRANSIENT_ERROR_PATTERNS)


def _run_gh_once(args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=GH_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise _TransientGhError(f"gh {' '.join(args)} がタイムアウトしました") from exc
    if result.returncode == 0:
        return result.stdout
    stderr = result.stderr.strip()
    if is_transient_gh_error(stderr):
        raise _TransientGhError(stderr)
    raise GitHubClientError(stderr)


def _run_gh(args: list[str], retryable: bool = True) -> str:
    """ghを実行し、標準出力を返す

    retryableの場合、一時的な通信エラーは間隔を空けて再試行する。
    二重実行で結果が変わる操作（作成・マージ）はretryable=Falseで呼ぶ。
    """
    attempts = GH_MAX_ATTEMPTS if retryable else 1
    for attempt in range(1, attempts + 1):
        try:
            return _run_gh_once(args)
        except _TransientGhError as exc:
            if attempt == attempts:
                raise GitHubClientError(str(exc)) from exc
            time.sleep(GH_RETRY_INTERVAL_SECONDS * attempt)
    raise AssertionError("unreachable")


def invalidate_issue_list_cache(repo: str) -> None:
    """指定リポジトリのIssue一覧キャッシュを破棄する"""
    _issue_list_cache.invalidate_repo(repo)


def clear_issue_list_cache() -> None:
    _issue_list_cache.clear()


def list_issues(repo: str, state: str = "open") -> list[dict]:
    """Issue一覧

    保持時間内の再取得はキャッシュを返す。
    """
    return _issue_list_cache.get_or_load((repo, state), lambda: _fetch_issues(repo, state))


def _fetch_issues(repo: str, state: str) -> list[dict]:
    output = _run_gh(
        [
            "issue", "list",
            "--repo", repo,
            "--state", state,
            "--limit", str(ISSUE_LIST_LIMIT),
            "--json", "number,title,state,url",
        ]
    )
    return json.loads(output)


def list_issues_closed_since(repo: str, since: datetime) -> list[dict]:
    """指定日時以降にクローズされたIssue一覧

    sinceはタイムゾーン付きで指定する。
    保持時間内の再取得はキャッシュを返す。
    """
    since_text = since.isoformat(timespec="seconds")
    key = (repo, CLOSED_SINCE_CACHE_KIND + since_text)
    return _issue_list_cache.get_or_load(key, lambda: _fetch_issues_closed_since(repo, since_text))


def _fetch_issues_closed_since(repo: str, since_text: str) -> list[dict]:
    output = _run_gh(
        [
            "issue", "list",
            "--repo", repo,
            "--state", "closed",
            "--search", f"closed:>={since_text}",
            "--limit", str(ISSUE_LIST_LIMIT),
            "--json", "number,title,state,url",
        ]
    )
    return json.loads(output)


def get_issue(repo: str, number: int) -> dict:
    output = _run_gh(
        ["issue", "view", str(number), "--repo", repo, "--json", "number,title,body,state,url"]
    )
    return json.loads(output)


def create_issue(repo: str, title: str, body: str) -> dict:
    output = _run_gh(
        ["issue", "create", "--repo", repo, "--title", title, "--body", body], retryable=False
    )
    url = output.strip()
    number = int(url.rsplit("/", 1)[-1])
    invalidate_issue_list_cache(repo)
    return {"number": number, "url": url}


def edit_issue_title(repo: str, number: int, title: str) -> None:
    _run_gh(["issue", "edit", str(number), "--repo", repo, "--title", title])
    invalidate_issue_list_cache(repo)


def close_issue(repo: str, number: int) -> None:
    _run_gh(["issue", "close", str(number), "--repo", repo])
    invalidate_issue_list_cache(repo)


def reopen_issue(repo: str, number: int) -> None:
    _run_gh(["issue", "reopen", str(number), "--repo", repo])
    invalidate_issue_list_cache(repo)


def close_pr(repo: str, number: int) -> None:
    _run_gh(["pr", "close", str(number), "--repo", repo])


def reopen_pr(repo: str, number: int) -> None:
    _run_gh(["pr", "reopen", str(number), "--repo", repo])


def get_pr_state(repo: str, number: int) -> dict:
    output = _run_gh(
        ["pr", "view", str(number), "--repo", repo, "--json", "number,isDraft,state,mergedAt"]
    )
    return json.loads(output)


def edit_pr_title(repo: str, number: int, title: str) -> None:
    _run_gh(["pr", "edit", str(number), "--repo", repo, "--title", title])


def edit_pr_body(repo: str, number: int, body: str) -> None:
    _run_gh(["pr", "edit", str(number), "--repo", repo, "--body", body])


def create_draft_pr(repo: str, base: str, head: str, title: str, body: str) -> dict:
    output = _run_gh(
        [
            "pr", "create",
            "--repo", repo,
            "--draft",
            "--base", base,
            "--head", head,
            "--title", title,
            "--body", body,
        ],
        retryable=False,
    )
    url = output.strip()
    number = int(url.rsplit("/", 1)[-1])
    return {"number": number, "url": url}


def mark_pr_ready(repo: str, number: int) -> None:
    _run_gh(["pr", "ready", str(number), "--repo", repo])


def list_pull_request_states(repo: str) -> list[dict]:
    output = _run_gh(
        [
            "pr", "list",
            "--repo", repo,
            "--state", "all",
            "--limit", str(PR_STATE_LIST_LIMIT),
            "--json", PR_STATE_FIELDS,
        ]
    )
    return json.loads(output)


def list_merged_pull_requests(repo: str) -> list[dict]:
    """マージ済PRの番号とマージコミット"""
    output = _run_gh(
        [
            "pr", "list",
            "--repo", repo,
            "--state", "merged",
            "--limit", str(PR_STATE_LIST_LIMIT),
            "--json", "number,mergeCommit",
        ]
    )
    return json.loads(output)


def get_pr_merge_commit(repo: str, number: int) -> str | None:
    output = _run_gh(["pr", "view", str(number), "--repo", repo, "--json", "mergeCommit"])
    return (json.loads(output).get("mergeCommit") or {}).get("oid")


def list_open_pull_requests(repo: str) -> list[dict]:
    output = _run_gh(
        [
            "pr", "list",
            "--repo", repo,
            "--state", "open",
            "--limit", str(PR_STATE_LIST_LIMIT),
            "--json", "number,isDraft,headRefName,baseRefName",
        ]
    )
    prs = json.loads(output)
    if len(prs) >= PR_STATE_LIST_LIMIT:
        logger.warning(
            "Open PRが取得上限%s件に達しました。上限を超えたPRは対象外の可能性があります: %s",
            PR_STATE_LIST_LIMIT,
            repo,
        )
    return prs


def get_pr_mergeable(repo: str, number: int) -> str:
    output = _run_gh(["pr", "view", str(number), "--repo", repo, "--json", "mergeable"])
    return json.loads(output)["mergeable"]


def merge_pull_request(repo: str, number: int) -> None:
    _run_gh(
        ["pr", "merge", str(number), "--repo", repo, "--merge", "--delete-branch"],
        retryable=False,
    )
