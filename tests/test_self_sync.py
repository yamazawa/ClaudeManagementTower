import pytest

from core import self_sync
from core.github_client import GitHubClientError
from core.pr_merger import PrMergeError
from core.self_sync import SelfSyncAlreadyRunning, read_result, run_self_sync, start_self_sync
from core.supervisor_control import COMMAND_RESTART_SERVER, COMMAND_RESTART_WORKERS


@pytest.fixture
def requested(monkeypatch, tmp_path):
    monkeypatch.setattr(self_sync.settings, "supervisor_control_dir", str(tmp_path))
    monkeypatch.setattr(self_sync, "pull_latest", lambda path, branch: None)
    monkeypatch.setattr(self_sync, "mark_prs_merged", lambda repo, numbers: None)
    commands = []
    monkeypatch.setattr(self_sync, "request_command", commands.append)
    return commands


def _prs(monkeypatch, prs):
    monkeypatch.setattr(self_sync, "list_open_pull_requests", lambda repo: prs)


def test_merges_only_non_draft_prs_and_restarts(monkeypatch, requested):
    _prs(monkeypatch, [{"number": 1, "isDraft": False}, {"number": 2, "isDraft": True}])
    merged = []
    monkeypatch.setattr(
        self_sync, "merge_pr_with_update", lambda repo, path, base, pr: merged.append(pr["number"])
    )

    run_self_sync("repo")

    assert merged == [1]
    assert read_result() == {"status": "done", "merged_pr_numbers": [1], "failed_prs": []}
    assert requested == [COMMAND_RESTART_SERVER, COMMAND_RESTART_WORKERS]


def test_marks_only_successfully_merged_prs(monkeypatch, requested):
    _prs(monkeypatch, [{"number": 1, "isDraft": False}, {"number": 2, "isDraft": False}])

    def merge(repo, path, base, pr):
        if pr["number"] == 2:
            raise PrMergeError("競合が解消されていません")

    monkeypatch.setattr(self_sync, "merge_pr_with_update", merge)
    marked = []
    monkeypatch.setattr(self_sync, "mark_prs_merged", lambda repo, numbers: marked.extend(numbers))

    run_self_sync("repo")

    assert marked == [1]


def test_continues_after_pr_failure(monkeypatch, requested):
    _prs(monkeypatch, [{"number": 1, "isDraft": False}, {"number": 2, "isDraft": False}])

    def merge(repo, path, base, pr):
        if pr["number"] == 1:
            raise PrMergeError("競合が解消されていません")

    monkeypatch.setattr(self_sync, "merge_pr_with_update", merge)

    run_self_sync("repo")

    assert read_result() == {
        "status": "done",
        "merged_pr_numbers": [2],
        "failed_prs": [{"number": 1, "error": "競合が解消されていません"}],
    }
    assert requested == [COMMAND_RESTART_SERVER, COMMAND_RESTART_WORKERS]


def test_github_failure_is_recorded_without_restart(monkeypatch, requested):
    def fail(repo):
        raise GitHubClientError("boom")

    monkeypatch.setattr(self_sync, "list_open_pull_requests", fail)

    run_self_sync("repo")

    assert read_result() == {"status": "failed", "error": "boom"}
    assert requested == []


def test_start_rejects_concurrent_run(monkeypatch, requested):
    _prs(monkeypatch, [])
    pending = []

    start_self_sync("repo", start_thread=pending.append)
    assert read_result() == {"status": "running"}
    with pytest.raises(SelfSyncAlreadyRunning):
        start_self_sync("repo", start_thread=pending.append)

    pending[0]()
    assert read_result()["status"] == "done"
    start_self_sync("repo", start_thread=lambda run: run())
