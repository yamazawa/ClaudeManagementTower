import json
import logging
import subprocess
from datetime import datetime

logger = logging.getLogger(__name__)

GH_TIMEOUT_SECONDS = 60
ISSUE_LIST_LIMIT = 200
PR_STATE_LIST_LIMIT = 200
# PR状態の同期と、管理塔外で作成されたPRの取り込みに使う項目
PR_STATE_FIELDS = "number,isDraft,state,mergedAt,title,headRefName,closingIssuesReferences"


class GitHubClientError(RuntimeError):
    pass


def _run_gh(args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=GH_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitHubClientError(f"gh {' '.join(args)} がタイムアウトしました") from exc
    if result.returncode != 0:
        raise GitHubClientError(result.stderr.strip())
    return result.stdout


def list_issues(repo: str, state: str = "open") -> list[dict]:
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
    """
    output = _run_gh(
        [
            "issue", "list",
            "--repo", repo,
            "--state", "closed",
            "--search", f"closed:>={since.isoformat(timespec='seconds')}",
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
    output = _run_gh(["issue", "create", "--repo", repo, "--title", title, "--body", body])
    url = output.strip()
    number = int(url.rsplit("/", 1)[-1])
    return {"number": number, "url": url}


def edit_issue_title(repo: str, number: int, title: str) -> None:
    _run_gh(["issue", "edit", str(number), "--repo", repo, "--title", title])


def close_issue(repo: str, number: int) -> None:
    _run_gh(["issue", "close", str(number), "--repo", repo])


def reopen_issue(repo: str, number: int) -> None:
    _run_gh(["issue", "reopen", str(number), "--repo", repo])


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
        ]
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
    _run_gh(["pr", "merge", str(number), "--repo", repo, "--merge", "--delete-branch"])
