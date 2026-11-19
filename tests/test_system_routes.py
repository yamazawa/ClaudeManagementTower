import pytest
from fastapi import HTTPException

from app.routes import system
from core.self_sync import SelfSyncAlreadyRunning
from core.supervisor_control import COMMAND_RESTART_SERVER, COMMAND_START_WORKERS


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


def test_sync_self_starts_background_run(monkeypatch):
    monkeypatch.setattr(system, "is_supervised", lambda: True)
    started = []
    monkeypatch.setattr(system, "start_self_sync", started.append)

    assert system.sync_self() == {"accepted": True}
    assert len(started) == 1


def test_sync_self_rejected_while_running(monkeypatch):
    monkeypatch.setattr(system, "is_supervised", lambda: True)

    def already_running(repo_path):
        raise SelfSyncAlreadyRunning("実行中")

    monkeypatch.setattr(system, "start_self_sync", already_running)

    with pytest.raises(HTTPException) as error:
        system.sync_self()
    assert error.value.status_code == 409


def test_get_sync_self_result_returns_saved_result(monkeypatch):
    monkeypatch.setattr(system, "read_result", lambda: {"status": "running"})

    assert system.get_sync_self_result() == {"status": "running"}


def test_get_sync_self_result_404_when_never_run(monkeypatch):
    monkeypatch.setattr(system, "read_result", lambda: None)

    with pytest.raises(HTTPException) as error:
        system.get_sync_self_result()
    assert error.value.status_code == 404


def test_rate_limits_returns_snapshot(monkeypatch):
    limits = {"five_hour": {"utilization": 0.4}, "seven_day": None}
    monkeypatch.setattr(system, "get_rate_limits", lambda: limits)

    assert system.rate_limits() == limits
