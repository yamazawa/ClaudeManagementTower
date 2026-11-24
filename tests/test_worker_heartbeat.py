import threading

import pytest

from core.config import settings
from worker.heartbeat import run_with_heartbeat


@pytest.fixture
def short_interval(monkeypatch):
    monkeypatch.setattr(settings, "job_heartbeat_interval_seconds", 0.01)


def test_run_with_heartbeat_calls_heartbeat_while_action_runs(short_interval):
    beaten = threading.Event()

    run_with_heartbeat(beaten.set, lambda: assert_beaten(beaten))

    assert beaten.is_set()


def assert_beaten(beaten: threading.Event) -> None:
    assert beaten.wait(timeout=5)


def test_run_with_heartbeat_stops_heartbeat_when_action_raises(short_interval):
    calls = []

    def failing() -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        run_with_heartbeat(lambda: calls.append(1), failing)

    count = len(calls)
    threading.Event().wait(0.05)
    assert len(calls) == count
