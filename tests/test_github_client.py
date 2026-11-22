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
            "--json", "number,isDraft,headRefName,baseRefName",
        ]
    ]


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
