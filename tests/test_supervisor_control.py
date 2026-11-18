import pytest

import run_all
from core.config import settings
from core.supervisor_control import (
    COMMAND_RESTART_SERVER,
    COMMAND_RESTART_WORKERS,
    COMMAND_START_WORKERS,
    request_command,
    take_requested_commands,
)


def test_try_acquire_singleton_lock_blocks_second_instance(tmp_path):
    lock_path = tmp_path / "supervisor.lock"

    first = run_all.try_acquire_singleton_lock(lock_path)
    second = run_all.try_acquire_singleton_lock(lock_path)

    assert first is not None
    assert second is None

    first.release()
    third = run_all.try_acquire_singleton_lock(lock_path)
    assert third is not None
    third.release()


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


class _FakePool:
    def __init__(self):
        self.running = False
        self.calls = []

    def is_running(self):
        return self.running

    def start(self):
        self.calls.append("start")
        self.running = True

    def stop(self):
        self.calls.append("stop")
        self.running = False

    def maintain(self):
        self.calls.append("maintain")


def _make_supervisor(monkeypatch):
    spawned = []

    def fake_spawn(self, args):
        process = _FakeProcess(args)
        spawned.append(process)
        return process

    monkeypatch.setattr(run_all.Supervisor, "_spawn", fake_spawn)
    pool = _FakePool()
    return run_all.Supervisor(pool=pool), spawned, pool


def test_restart_server_stops_old_and_starts_new(monkeypatch):
    supervisor, spawned, _ = _make_supervisor(monkeypatch)
    supervisor.start_server()

    supervisor.handle(COMMAND_RESTART_SERVER)

    assert spawned[0].terminated
    assert supervisor.server is spawned[1]


def test_start_workers_skips_when_running(monkeypatch):
    supervisor, _, pool = _make_supervisor(monkeypatch)
    supervisor.start_workers()

    supervisor.handle(COMMAND_START_WORKERS)

    assert pool.calls == ["start"]


def test_restart_workers_restarts_pool(monkeypatch):
    supervisor, _, pool = _make_supervisor(monkeypatch)
    supervisor.start_workers()

    supervisor.handle(COMMAND_RESTART_WORKERS)

    assert pool.calls == ["start", "start"]


def test_tick_handles_requests_then_maintains_pool(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "supervisor_control_dir", str(tmp_path))
    supervisor, _, pool = _make_supervisor(monkeypatch)
    request_command(COMMAND_START_WORKERS)

    supervisor.tick()

    assert pool.calls == ["start", "maintain"]
