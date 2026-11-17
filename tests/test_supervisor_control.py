import pytest

import run_all
from core.supervisor_control import (
    COMMAND_RESTART_SERVER,
    COMMAND_RESTART_WORKERS,
    COMMAND_START_WORKERS,
    request_command,
    take_requested_commands,
)


def test_request_then_take_returns_command_once(tmp_path):
    control_dir = str(tmp_path / "control")
    request_command(COMMAND_RESTART_SERVER, control_dir)
    request_command(COMMAND_RESTART_SERVER, control_dir)

    assert take_requested_commands(control_dir) == [COMMAND_RESTART_SERVER]
    assert take_requested_commands(control_dir) == []


def test_take_without_control_dir_returns_empty(tmp_path):
    assert take_requested_commands(str(tmp_path / "missing")) == []


def test_request_unknown_command_raises(tmp_path):
    with pytest.raises(ValueError):
        request_command("unknown", str(tmp_path))


class _FakeProcess:
    def __init__(self, args):
        self.args = args
        self.returncode = None
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 1

    def wait(self, timeout=None):
        return self.returncode


def _make_supervisor(monkeypatch):
    spawned = []

    def fake_spawn(self, args):
        process = _FakeProcess(args)
        spawned.append(process)
        return process

    monkeypatch.setattr(run_all.Supervisor, "_spawn", fake_spawn)
    return run_all.Supervisor(), spawned


def test_restart_server_stops_old_and_starts_new(monkeypatch):
    supervisor, spawned = _make_supervisor(monkeypatch)
    supervisor.start_server()

    supervisor.handle(COMMAND_RESTART_SERVER)

    assert spawned[0].terminated
    assert supervisor.server is spawned[1]


def test_start_workers_skips_when_running(monkeypatch):
    supervisor, spawned = _make_supervisor(monkeypatch)
    supervisor.start_workers()

    supervisor.handle(COMMAND_START_WORKERS)

    assert len(spawned) == 1


def test_start_workers_restarts_after_exit(monkeypatch):
    supervisor, spawned = _make_supervisor(monkeypatch)
    supervisor.start_workers()
    spawned[0].returncode = 0

    supervisor.handle(COMMAND_START_WORKERS)

    assert supervisor.workers is spawned[1]


def test_restart_workers_stops_old_and_starts_new(monkeypatch):
    supervisor, spawned = _make_supervisor(monkeypatch)
    supervisor.start_workers()

    supervisor.handle(COMMAND_RESTART_WORKERS)

    assert spawned[0].terminated
    assert supervisor.workers is spawned[1]
