from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import sessionmaker

from core.db import init_db, make_engine
from core.job_queue import (
    claim_next_job,
    cleanup_stale_workers,
    finish_job,
    heartbeat_job,
    recover_stale_jobs,
    register_worker,
    set_worker_state,
)
from core.models import ExecutionJob, Subtask, Worker


def _setup(tmp_path):
    engine = make_engine(str(tmp_path / "test.db"))
    init_db(bind=engine)
    return engine, sessionmaker(bind=engine)


def _add_subtask_and_jobs(session_factory, job_count: int) -> int:
    with session_factory() as session:
        subtask = Subtask(
            project_id=1,
            github_issue_number=1,
            title="テストサブタスク",
            instruction="テスト用",
            branch_name="issue-1-test",
            lifecycle_state="draft",
        )
        session.add(subtask)
        session.commit()
        session.refresh(subtask)
        for _ in range(job_count):
            session.add(ExecutionJob(subtask_id=subtask.id, status="queued"))
        session.commit()
        return subtask.id


def test_claim_next_job_returns_queued_job(tmp_path):
    engine, session_factory = _setup(tmp_path)
    _add_subtask_and_jobs(session_factory, job_count=1)
    worker_id = register_worker("worker-a", session_factory=session_factory)

    job = claim_next_job(worker_id, bind=engine, session_factory=session_factory)

    assert job is not None
    with session_factory() as session:
        claimed = session.get(ExecutionJob, job["job_id"])
        assert claimed.status == "running"
        assert claimed.worker_id == worker_id


def test_claim_next_job_excludes_same_subtask_while_running(tmp_path):
    engine, session_factory = _setup(tmp_path)
    _add_subtask_and_jobs(session_factory, job_count=2)
    worker_id = register_worker("worker-a", session_factory=session_factory)

    first = claim_next_job(worker_id, bind=engine, session_factory=session_factory)
    second = claim_next_job(worker_id, bind=engine, session_factory=session_factory)

    assert first is not None
    assert second is None

    finish_job(first["job_id"], status="succeeded", exit_code=0, session_factory=session_factory)
    third = claim_next_job(worker_id, bind=engine, session_factory=session_factory)

    assert third is not None
    assert third["job_id"] != first["job_id"]


def test_set_worker_state_updates_row(tmp_path):
    _, session_factory = _setup(tmp_path)
    worker_id = register_worker("worker-a", session_factory=session_factory)

    set_worker_state(worker_id, state="busy", current_job_id=42, session_factory=session_factory)

    with session_factory() as session:
        from core.models import Worker

        worker = session.get(Worker, worker_id)
        assert worker.state == "busy"
        assert worker.current_job_id == 42


def test_recover_stale_jobs_flags_jobs_without_recent_heartbeat(tmp_path):
    engine, session_factory = _setup(tmp_path)
    _add_subtask_and_jobs(session_factory, job_count=1)
    worker_id = register_worker("worker-a", session_factory=session_factory)
    job = claim_next_job(worker_id, bind=engine, session_factory=session_factory)

    with session_factory() as session:
        stale = session.get(ExecutionJob, job["job_id"])
        stale.heartbeat_at = datetime.now(timezone.utc) - timedelta(seconds=120)
        session.commit()

    recovered = recover_stale_jobs(timeout_seconds=60, session_factory=session_factory)

    assert recovered == [job["job_id"]]
    with session_factory() as session:
        reloaded = session.get(ExecutionJob, job["job_id"])
        assert reloaded.status == "needs_attention"


def test_cleanup_stale_workers_removes_dead_worker_rows(tmp_path):
    _, session_factory = _setup(tmp_path)
    worker_id = register_worker("worker-dead", session_factory=session_factory)

    with session_factory() as session:
        worker = session.get(Worker, worker_id)
        worker.heartbeat_at = datetime.now(timezone.utc) - timedelta(seconds=120)
        session.commit()

    removed = cleanup_stale_workers(timeout_seconds=30, session_factory=session_factory)

    assert removed == [worker_id]
    with session_factory() as session:
        assert session.get(Worker, worker_id) is None


def test_cleanup_stale_workers_keeps_recently_heartbeaten_workers(tmp_path):
    _, session_factory = _setup(tmp_path)
    worker_id = register_worker("worker-alive", session_factory=session_factory)

    removed = cleanup_stale_workers(timeout_seconds=30, session_factory=session_factory)

    assert removed == []
    with session_factory() as session:
        assert session.get(Worker, worker_id) is not None


def test_recover_stale_jobs_keeps_recently_heartbeaten_jobs(tmp_path):
    engine, session_factory = _setup(tmp_path)
    _add_subtask_and_jobs(session_factory, job_count=1)
    worker_id = register_worker("worker-a", session_factory=session_factory)
    job = claim_next_job(worker_id, bind=engine, session_factory=session_factory)

    heartbeat_job(job["job_id"], worker_id, session_factory=session_factory)
    recovered = recover_stale_jobs(timeout_seconds=60, session_factory=session_factory)

    assert recovered == []
    with session_factory() as session:
        reloaded = session.get(ExecutionJob, job["job_id"])
        assert reloaded.status == "running"
