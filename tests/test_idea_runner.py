import pytest
from sqlalchemy.orm import sessionmaker

import worker.idea_runner as idea_runner
import worker.main as worker_main
from core.db import init_db, make_engine
from core.idea_context import build_idea_prompt
from core.idea_queue import IdeaJobStatus, finish_idea_job
from core.ideas import save_proposals
from core.models import Idea, IdeaJob, Project


@pytest.fixture(autouse=True)
def not_rate_limited(monkeypatch):
    monkeypatch.setattr(worker_main, "_is_rate_limited", lambda: False)


@pytest.fixture
def session_factory(tmp_path, monkeypatch):
    engine = make_engine(str(tmp_path / "test.db"))
    init_db(bind=engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        session.add(Project(id=1, name="p", github_repo="owner/repo", repo_path=str(tmp_path), default_branch="master"))
        session.add(IdeaJob(id=1, project_id=1, status=IdeaJobStatus.RUNNING))
        session.commit()
    monkeypatch.setattr(idea_runner, "SessionLocal", factory)
    monkeypatch.setattr(
        idea_runner, "finish_idea_job",
        lambda *a, **k: finish_idea_job(*a, **k, session_factory=factory),
    )
    monkeypatch.setattr(
        idea_runner, "save_proposals",
        lambda *a, **k: save_proposals(*a, **k, session_factory=factory),
    )
    monkeypatch.setattr(
        idea_runner, "build_idea_prompt",
        lambda *a, **k: build_idea_prompt(*a, **k, session_factory=factory, issue_lister=lambda repo: []),
    )
    monkeypatch.setattr(idea_runner, "set_worker_state", lambda *a, **k: True)
    return factory


def _runner(result_text):
    calls = []

    async def fake_runner(prompt, repo_path):
        calls.append((prompt, repo_path))
        return "sid", result_text

    return fake_runner, calls


def _job(factory):
    with factory() as session:
        job = session.get(IdeaJob, 1)
        session.expunge(job)
        return job


def test_process_idea_job_saves_proposals(session_factory, tmp_path):
    runner, calls = _runner('```json\n[{"title": "a"}, {"title": "b"}]\n```')

    idea_runner.process_idea_job({"idea_job_id": 1, "project_id": 1}, 1, claude_runner=runner)

    job = _job(session_factory)
    assert job.status == IdeaJobStatus.SUCCEEDED
    assert job.claude_session_id == "sid"
    assert job.result_summary == "2件の提案を保存しました"
    assert calls[0][1] == str(tmp_path)
    with session_factory() as session:
        assert [i.title for i in session.query(Idea).order_by(Idea.id)] == ["a", "b"]


def test_process_idea_job_fails_on_unparsable_result(session_factory):
    runner, _ = _runner("提案はありません")

    idea_runner.process_idea_job({"idea_job_id": 1, "project_id": 1}, 1, claude_runner=runner)

    job = _job(session_factory)
    assert job.status == IdeaJobStatus.FAILED
    assert "提案はありません" in job.error_message


def test_process_idea_job_records_exception(session_factory):
    async def failing_runner(prompt, repo_path):
        raise RuntimeError("claude down")

    idea_runner.process_idea_job({"idea_job_id": 1, "project_id": 1}, 1, claude_runner=failing_runner)

    job = _job(session_factory)
    assert job.status == IdeaJobStatus.FAILED
    assert job.error_message == "claude down"


def test_process_idea_job_marks_rate_limited(session_factory):
    async def limited_runner(prompt, repo_path):
        raise RuntimeError("You've hit your 5-hour limit · resets 10pm (exit code: 1)")

    idea_runner.process_idea_job({"idea_job_id": 1, "project_id": 1}, 1, claude_runner=limited_runner)

    assert _job(session_factory).status == IdeaJobStatus.RATE_LIMITED


def test_process_next_job_skips_claim_while_rate_limited(monkeypatch):
    monkeypatch.setattr(worker_main, "_is_rate_limited", lambda: True)
    monkeypatch.setattr(worker_main, "claim_next_job", lambda worker_id: pytest.fail("not expected"))
    monkeypatch.setattr(worker_main, "claim_next_idea_job", lambda worker_id: pytest.fail("not expected"))

    assert worker_main._process_next_job(1) is False


def test_process_next_job_prefers_execution_job(monkeypatch):
    processed = []
    monkeypatch.setattr(worker_main, "claim_next_job", lambda worker_id: {"job_id": 5, "subtask_id": 1})
    monkeypatch.setattr(worker_main, "claim_next_idea_job", lambda worker_id: pytest.fail("not expected"))
    monkeypatch.setattr(worker_main, "process_job", lambda job, worker_id: processed.append("job"))

    assert worker_main._process_next_job(1) is True
    assert processed == ["job"]


def test_process_next_job_runs_idea_job_when_queue_empty(monkeypatch):
    processed = []
    monkeypatch.setattr(worker_main, "claim_next_job", lambda worker_id: None)
    monkeypatch.setattr(worker_main, "claim_next_idea_job", lambda worker_id: {"idea_job_id": 2, "project_id": 1})
    monkeypatch.setattr(worker_main, "process_idea_job", lambda job, worker_id: processed.append(job["idea_job_id"]))

    assert worker_main._process_next_job(1) is True
    assert processed == [2]


def test_process_next_job_returns_false_without_jobs(monkeypatch):
    monkeypatch.setattr(worker_main, "claim_next_job", lambda worker_id: None)
    monkeypatch.setattr(worker_main, "claim_next_idea_job", lambda worker_id: None)

    assert worker_main._process_next_job(1) is False
