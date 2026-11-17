import json
import subprocess

GH_TIMEOUT_SECONDS = 60
ISSUE_LIST_LIMIT = 200


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
            "--json", "number,title,state",
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


def edit_pr_title(repo: str, number: int, title: str) -> None:
    _run_gh(["pr", "edit", str(number), "--repo", repo, "--title", title])


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


def get_pr(repo: str, number: int) -> dict:
    output = _run_gh(
        [
            "pr", "view", str(number),
            "--repo", repo,
            "--json", "number,isDraft,state,mergedAt,url",
        ]
    )
    return json.loads(output)


def list_open_pull_requests(repo: str) -> list[dict]:
    output = _run_gh(
        ["pr", "list", "--repo", repo, "--state", "open", "--json", "number,isDraft"]
    )
    return json.loads(output)


def merge_pull_request(repo: str, number: int) -> None:
    _run_gh(["pr", "merge", str(number), "--repo", repo, "--merge", "--delete-branch"])
