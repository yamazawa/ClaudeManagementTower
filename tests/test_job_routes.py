import pytest
from sqlalchemy.orm import sessionmaker

from app.routes import jobs, projects
from core.db import init_db, make_engine
from core.models import ExecutionJob


@pytest.fixture
def session_factory(tmp_path, monkeypatch):
    engine = make_engine(str(tmp_path / "test.db"))
    init_db(bind=engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(jobs, "SessionLocal", factory)
    with factory() as session:
        session.add(ExecutionJob(subtask_id=1, status="failed", error_message="TLS handshake timeout"))
        session.commit()
    return factory


def test_get_job_returns_error_message(session_factory):
    assert jobs.get_job(1)["error_message"] == "TLS handshake timeout"


def test_latest_job_summary_returns_error_message(session_factory):
    with session_factory() as session:
        summary = projects._latest_job_summary(session, subtask_id=1)

    assert summary == {"id": 1, "status": "failed", "has_report": False, "error_message": "TLS handshake timeout"}
