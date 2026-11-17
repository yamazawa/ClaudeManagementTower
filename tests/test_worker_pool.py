from sqlalchemy.orm import sessionmaker

from core.config import settings
from core.db import init_db, make_engine
from core.job_queue import make_process_identifier, register_worker
from core.models import Worker
from worker.pool import WorkerPool


class _FakeProcess:
    def __init__(self):
        self.returncode = None
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 1

    def wait(self, timeout=None):
        return self.returncode


class _FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def _make_pool(tmp_path, count=3):
    engine = make_engine(str(tmp_path / "test.db"))
    init_db(bind=engine)
    session_factory = sessionmaker(bind=engine)
    spawned, killed = [], []
    clock = _FakeClock()

    def spawn():
        spawned.append(_FakeProcess())
        return spawned[-1]

    pool = WorkerPool(count, spawn=spawn, kill=killed.append, session_factory=session_factory, clock=clock)
    return pool, spawned, killed, session_factory, clock


def test_start_spawns_configured_count(tmp_path):
    pool, spawned, _, _, _ = _make_pool(tmp_path, count=3)

    pool.start()

    assert len(spawned) == 3
    assert pool.is_running()


def test_start_twice_keeps_configured_count(tmp_path):
    pool, spawned, _, _, _ = _make_pool(tmp_path, count=3)

    pool.start()
    pool.start()

    assert all(process.terminated for process in spawned[:3])
    assert [p.poll() for p in pool.processes()] == [None, None, None]


def test_start_kills_registered_workers_and_clears_rows(tmp_path):
    pool, _, killed, session_factory, _ = _make_pool(tmp_path)
    register_worker(make_process_identifier(111), session_factory=session_factory)
    register_worker(make_process_identifier(222), session_factory=session_factory)

    pool.start()

    assert sorted(killed) == [111, 222]
    with session_factory() as session:
        assert session.query(Worker).count() == 0


def test_stop_terminates_all_processes(tmp_path):
    pool, spawned, _, _, _ = _make_pool(tmp_path)
    pool.start()

    pool.stop()

    assert all(process.terminated for process in spawned)
    assert not pool.is_running()


def test_maintain_respawns_exited_worker_after_delay(tmp_path):
    pool, spawned, _, _, clock = _make_pool(tmp_path, count=2)
    pool.start()
    spawned[0].returncode = 1

    pool.maintain()
    assert len(spawned) == 2

    clock.now += settings.worker_respawn_delay_seconds
    pool.maintain()

    assert len(spawned) == 3
    assert pool.processes() == [spawned[2], spawned[1]]


def test_maintain_keeps_running_workers(tmp_path):
    pool, spawned, _, _, clock = _make_pool(tmp_path, count=2)
    pool.start()
    clock.now += settings.worker_respawn_delay_seconds

    pool.maintain()

    assert len(spawned) == 2
