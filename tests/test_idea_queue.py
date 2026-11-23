from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from core import idea_queue
from core.db import init_db, make_engine
from core.idea_queue import IdeaJobStatus
from core.models import IdeaJob, Project


@pytest.fixture
def db(tmp_path):
    engine = make_engine(str(tmp_path / "test.db"))
    init_db(bind=engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        session.add(Project(id=1, name="p", github_repo="owner/repo", repo_path="C:/repo", default_branch="master"))
        session.add(Project(id=2, name="q", github_repo="owner/other", repo_path="C:/other", default_branch="master"))
        session.commit()
    return engine, factory


def test_enqueue_rejects_unknown_project(db):
    _, factory = db
    with pytest.raises(idea_queue.IdeaProjectNotFound):
        idea_queue.enqueue_idea_job(99, session_factory=factory)


def test_enqueue_refuses_while_active_but_allows_other_project(db):
    _, factory = db
    idea_queue.enqueue_idea_job(1, session_factory=factory)

    with pytest.raises(idea_queue.IdeaJobAlreadyActive):
        idea_queue.enqueue_idea_job(1, session_factory=factory)
    assert idea_queue.enqueue_idea_job(2, session_factory=factory)["status"] == IdeaJobStatus.QUEUED


def test_enqueue_allowed_after_finish(db):
    _, factory = db
    job = idea_queue.enqueue_idea_job(1, session_factory=factory)
    idea_queue.finish_idea_job(job["id"], IdeaJobStatus.FAILED, error_message="x", session_factory=factory)

    assert idea_queue.enqueue_idea_job(1, session_factory=factory)["id"] != job["id"]


def test_claim_returns_oldest_queued_job_once(db):
    engine, factory = db
    first = idea_queue.enqueue_idea_job(1, " テスト不足 \n", session_factory=factory)
    idea_queue.enqueue_idea_job(2, session_factory=factory)

    claimed = idea_queue.claim_next_idea_job(7, bind=engine, session_factory=factory)

    assert first["focus"] == "テスト不足"
    assert claimed == {"idea_job_id": first["id"], "project_id": 1, "focus": "テスト不足"}
    with factory() as session:
        job = session.get(IdeaJob, first["id"])
        assert job.status == IdeaJobStatus.RUNNING
        assert job.worker_id == 7
    assert idea_queue.claim_next_idea_job(7, bind=engine, session_factory=factory)["project_id"] == 2
    assert idea_queue.claim_next_idea_job(7, bind=engine, session_factory=factory) is None


def test_finish_records_result(db):
    engine, factory = db
    job = idea_queue.enqueue_idea_job(1, session_factory=factory)
    idea_queue.claim_next_idea_job(1, bind=engine, session_factory=factory)

    idea_queue.finish_idea_job(job["id"], IdeaJobStatus.SUCCEEDED, "sid", "3件", session_factory=factory)

    latest = idea_queue.latest_idea_job(1, session_factory=factory)
    assert latest["status"] == IdeaJobStatus.SUCCEEDED
    assert latest["result_summary"] == "3件"
    assert latest["ended_at"] is not None


def test_latest_idea_job_is_none_without_jobs(db):
    _, factory = db
    assert idea_queue.latest_idea_job(1, session_factory=factory) is None


def test_recover_stale_idea_jobs(db):
    _, factory = db
    old = datetime.now(timezone.utc) - timedelta(seconds=600)
    with factory() as session:
        session.add(IdeaJob(id=1, project_id=1, status=IdeaJobStatus.RUNNING, heartbeat_at=old))
        session.add(IdeaJob(id=2, project_id=2, status=IdeaJobStatus.RUNNING, heartbeat_at=datetime.now(timezone.utc)))
        session.commit()

    assert idea_queue.recover_stale_idea_jobs(60, session_factory=factory) == [1]
    with factory() as session:
        assert session.get(IdeaJob, 1).status == IdeaJobStatus.NEEDS_ATTENTION
        assert session.get(IdeaJob, 2).status == IdeaJobStatus.RUNNING
