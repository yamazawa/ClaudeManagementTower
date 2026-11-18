import pytest
from fastapi import HTTPException

from app.routes import system
from core.github_client import GitHubClientError
from core.supervisor_control import (
    COMMAND_RESTART_SERVER,
    COMMAND_RESTART_WORKERS,
    COMMAND_START_WORKERS,
)


def test_request_rejected_when_not_supervised(monkeypatch):
    monkeypatch.setattr(system, "is_supervised", lambda: False)

    with pytest.raises(HTTPException) as error:
        system.restart_server()

    assert error.value.status_code == 409


@pytest.mark.parametrize(
    ("endpoint", "command"),
    [
        (system.restart_server, COMMAND_RESTART_SERVER),
        (system.start_workers, COMMAND_START_WORKERS),
    ],
)
def test_request_forwarded_when_supervised(monkeypatch, endpoint, command):
    requested = []
    monkeypatch.setattr(system, "is_supervised", lambda: True)
    monkeypatch.setattr(system, "request_command", requested.append)

    assert endpoint() == {"accepted": True}
    assert requested == [command]


def test_cleanup_workers_returns_removed_ids(monkeypatch):
    monkeypatch.setattr(system, "cleanup_stale_workers", lambda timeout: [3])
    monkeypatch.setattr(system, "recover_stale_jobs", lambda timeout: [7])

    assert system.cleanup_workers() == {"removed_worker_ids": [3], "recovered_job_ids": [7]}


def test_sync_self_rejected_when_not_supervised(monkeypatch):
    monkeypatch.setattr(system, "is_supervised", lambda: False)

    with pytest.raises(HTTPException) as error:
        system.sync_self()

    assert error.value.status_code == 409


def test_sync_self_merges_only_non_draft_prs(monkeypatch):
    monkeypatch.setattr(system, "is_supervised", lambda: True)
    monkeypatch.setattr(
        system,
        "list_open_pull_requests",
        lambda repo: [{"number": 1, "isDraft": False}, {"number": 2, "isDraft": True}],
    )
    merged = []
    monkeypatch.setattr(system, "merge_pull_request", lambda repo, number: merged.append(number))
    monkeypatch.setattr(system, "pull_latest", lambda path, branch: None)
    marked = []
    monkeypatch.setattr(system, "mark_prs_merged", lambda repo, numbers: marked.extend(numbers))
    requested = []
    monkeypatch.setattr(system, "request_command", requested.append)

    result = system.sync_self()

    assert merged == [1]
    assert marked == [1]
    assert result == {"merged_pr_numbers": [1]}
    assert requested == [COMMAND_RESTART_SERVER, COMMAND_RESTART_WORKERS]


def test_sync_self_raises_on_github_failure(monkeypatch):
    monkeypatch.setattr(system, "is_supervised", lambda: True)

    def fail(repo):
        raise GitHubClientError("boom")

    monkeypatch.setattr(system, "list_open_pull_requests", fail)

    with pytest.raises(HTTPException) as error:
        system.sync_self()
    assert error.value.status_code == 500
