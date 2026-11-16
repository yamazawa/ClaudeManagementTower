import pytest
from fastapi import HTTPException

from app.routes import system
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
