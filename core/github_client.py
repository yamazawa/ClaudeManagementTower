import json
import subprocess

GH_TIMEOUT_SECONDS = 60


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


def list_issues(repo: str) -> list[dict]:
    output = _run_gh(["issue", "list", "--repo", repo, "--json", "number,title,state"])
    return json.loads(output)


def get_issue(repo: str, number: int) -> dict:
    output = _run_gh(
        ["issue", "view", str(number), "--repo", repo, "--json", "number,title,body,state,url"]
    )
    return json.loads(output)


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
