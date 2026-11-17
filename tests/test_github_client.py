import subprocess

import pytest

from core import github_client
from core.github_client import GitHubClientError, edit_issue_title, edit_pr_title


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


def test_edit_pr_title_raises_on_gh_failure(monkeypatch):
    calls = []
    monkeypatch.setattr(
        github_client.subprocess, "run", _fake_run(calls, returncode=1, stderr="not found")
    )

    with pytest.raises(GitHubClientError, match="not found"):
        edit_pr_title("owner/repo", 34, "PRタイトル")
