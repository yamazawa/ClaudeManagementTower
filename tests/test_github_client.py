import json
import subprocess
from datetime import datetime, timedelta, timezone

import pytest

from core import github_client
from core.github_client import (
    GitHubClientError,
    edit_issue_title,
    edit_pr_body,
    edit_pr_title,
    get_pr_mergeable,
    list_issues,
    list_issues_closed_since,
    list_open_pull_requests,
    merge_pull_request,
)


def _fake_run(calls: list, returncode: int = 0, stderr: str = ""):
    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, returncode, stdout="", stderr=stderr)

    return run


def test_edit_issue_title_runs_gh_issue_edit(monkeypatch):
    calls = []
    monkeypatch.setattr(github_client.subprocess, "run", _fake_run(calls))

    edit_issue_title("owner/repo", 12, "新しいタイトル")

    assert calls == [
        ["gh", "issue", "edit", "12", "--repo", "owner/repo", "--title", "新しいタイトル"]
    ]


def test_edit_pr_title_runs_gh_pr_edit(monkeypatch):
    calls = []
    monkeypatch.setattr(github_client.subprocess, "run", _fake_run(calls))

    edit_pr_title("owner/repo", 34, "PRタイトル")

    assert calls == [["gh", "pr", "edit", "34", "--repo", "owner/repo", "--title", "PRタイトル"]]


def test_edit_pr_body_runs_gh_pr_edit(monkeypatch):
    calls = []
    monkeypatch.setattr(github_client.subprocess, "run", _fake_run(calls))

    edit_pr_body("owner/repo", 34, "Related to #5")

    assert calls == [["gh", "pr", "edit", "34", "--repo", "owner/repo", "--body", "Related to #5"]]


def test_edit_pr_title_raises_on_gh_failure(monkeypatch):
    calls = []
    monkeypatch.setattr(
        github_client.subprocess, "run", _fake_run(calls, returncode=1, stderr="not found")
    )

    with pytest.raises(GitHubClientError, match="not found"):
        edit_pr_title("owner/repo", 34, "PRタイトル")


def test_list_open_pull_requests_parses_json(monkeypatch):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        stdout = json.dumps([{"number": 1, "isDraft": False}, {"number": 2, "isDraft": True}])
        return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(github_client.subprocess, "run", run)

    result = list_open_pull_requests("owner/repo")

    assert result == [{"number": 1, "isDraft": False}, {"number": 2, "isDraft": True}]
    assert calls == [
        [
            "gh", "pr", "list", "--repo", "owner/repo", "--state", "open",
            "--limit", str(github_client.PR_STATE_LIST_LIMIT),
            "--json", "number,isDraft,headRefName,baseRefName",
        ]
    ]


def _fake_run_returning(prs: list[dict]):
    def run(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(prs), stderr="")

    return run


def test_list_open_pull_requests_warns_when_limit_reached(monkeypatch, caplog):
    monkeypatch.setattr(github_client, "PR_STATE_LIST_LIMIT", 2)
    monkeypatch.setattr(
        github_client.subprocess, "run", _fake_run_returning([{"number": 1}, {"number": 2}])
    )

    with caplog.at_level("WARNING", logger=github_client.__name__):
        list_open_pull_requests("owner/repo")

    assert "取得上限2件" in caplog.text


def test_list_open_pull_requests_does_not_warn_below_limit(monkeypatch, caplog):
    monkeypatch.setattr(github_client, "PR_STATE_LIST_LIMIT", 2)
    monkeypatch.setattr(github_client.subprocess, "run", _fake_run_returning([{"number": 1}]))

    with caplog.at_level("WARNING", logger=github_client.__name__):
        list_open_pull_requests("owner/repo")

    assert caplog.text == ""


def test_get_pr_mergeable_returns_state(monkeypatch):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout='{"mergeable": "CONFLICTING"}', stderr="")

    monkeypatch.setattr(github_client.subprocess, "run", run)

    assert get_pr_mergeable("owner/repo", 5) == "CONFLICTING"
    assert calls == [["gh", "pr", "view", "5", "--repo", "owner/repo", "--json", "mergeable"]]


@pytest.mark.parametrize("state", ["open", "closed", "all"])
def test_list_issues_passes_state(monkeypatch, state):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        stdout = json.dumps([{"number": 3, "title": "t", "state": "OPEN"}])
        return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(github_client.subprocess, "run", run)

    result = list_issues("owner/repo", state)

    assert result == [{"number": 3, "title": "t", "state": "OPEN"}]
    assert calls == [
        [
            "gh", "issue", "list",
            "--repo", "owner/repo",
            "--state", state,
            "--limit", str(github_client.ISSUE_LIST_LIMIT),
            "--json", "number,title,state,url",
        ]
    ]


def test_list_issues_defaults_to_open(monkeypatch):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="[]", stderr="")

    monkeypatch.setattr(github_client.subprocess, "run", run)

    list_issues("owner/repo")

    assert calls[0][calls[0].index("--state") + 1] == "open"


def test_list_issues_closed_since_searches_closed_date(monkeypatch):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        stdout = json.dumps([{"number": 4, "title": "t", "state": "CLOSED"}])
        return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(github_client.subprocess, "run", run)
    since = datetime(2026, 11, 22, tzinfo=timezone(timedelta(hours=9)))

    result = list_issues_closed_since("owner/repo", since)

    assert result == [{"number": 4, "title": "t", "state": "CLOSED"}]
    assert calls == [
        [
            "gh", "issue", "list",
            "--repo", "owner/repo",
            "--state", "closed",
            "--search", "closed:>=2026-11-22T00:00:00+09:00",
            "--limit", str(github_client.ISSUE_LIST_LIMIT),
            "--json", "number,title,state,url",
        ]
    ]


def test_merge_pull_request_runs_gh_pr_merge(monkeypatch):
    calls = []
    monkeypatch.setattr(github_client.subprocess, "run", _fake_run(calls))

    merge_pull_request("owner/repo", 7)

    assert calls == [
        ["gh", "pr", "merge", "7", "--repo", "owner/repo", "--merge", "--delete-branch"]
    ]


def _sequence_run(calls: list, results: list[tuple[int, str]]):
    def run(args, **kwargs):
        calls.append(args)
        returncode, stderr = results[len(calls) - 1]
        return subprocess.CompletedProcess(args, returncode, stdout="ok", stderr=stderr)

    return run


@pytest.fixture
def sleeps(monkeypatch):
    recorded = []
    monkeypatch.setattr(github_client.time, "sleep", recorded.append)
    return recorded


TLS_ERROR = "Post https://api.github.com/graphql: net/http: TLS handshake timeout"


def test_run_gh_retries_transient_error_then_succeeds(monkeypatch, sleeps):
    calls = []
    monkeypatch.setattr(
        github_client.subprocess, "run", _sequence_run(calls, [(1, TLS_ERROR), (0, "")])
    )

    assert github_client._run_gh(["pr", "ready", "1"]) == "ok"
    assert len(calls) == 2
    assert sleeps == [github_client.GH_RETRY_INTERVAL_SECONDS]


def test_run_gh_gives_up_after_max_attempts(monkeypatch, sleeps):
    calls = []
    results = [(1, "HTTP 502: Bad Gateway")] * github_client.GH_MAX_ATTEMPTS
    monkeypatch.setattr(github_client.subprocess, "run", _sequence_run(calls, results))

    with pytest.raises(GitHubClientError, match="HTTP 502"):
        github_client._run_gh(["pr", "ready", "1"])
    assert len(calls) == github_client.GH_MAX_ATTEMPTS
    assert len(sleeps) == github_client.GH_MAX_ATTEMPTS - 1


def test_run_gh_retries_timeout(monkeypatch, sleeps):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            raise subprocess.TimeoutExpired(args, github_client.GH_TIMEOUT_SECONDS)
        return subprocess.CompletedProcess(args, 0, stdout="ok", stderr="")

    monkeypatch.setattr(github_client.subprocess, "run", run)

    assert github_client._run_gh(["pr", "view", "1"]) == "ok"
    assert len(calls) == 2


def test_run_gh_does_not_retry_permanent_error(monkeypatch, sleeps):
    calls = []
    monkeypatch.setattr(github_client.subprocess, "run", _fake_run(calls, 1, "not found"))

    with pytest.raises(GitHubClientError, match="not found"):
        github_client._run_gh(["pr", "view", "1"])
    assert len(calls) == 1
    assert sleeps == []


@pytest.mark.parametrize(
    "action",
    [
        lambda: github_client.create_issue("owner/repo", "t", "b"),
        lambda: github_client.create_draft_pr("owner/repo", "master", "head", "t", "b"),
        lambda: github_client.merge_pull_request("owner/repo", 7),
    ],
)
def test_non_idempotent_operations_are_not_retried(monkeypatch, sleeps, action):
    calls = []
    monkeypatch.setattr(github_client.subprocess, "run", _fake_run(calls, 1, TLS_ERROR))

    with pytest.raises(GitHubClientError, match="TLS handshake timeout"):
        action()
    assert len(calls) == 1
    assert sleeps == []
