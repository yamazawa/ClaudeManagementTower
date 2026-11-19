import pytest
from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker

from app.routes import subtasks
from core.db import init_db, make_engine
from core.models import ExecutionJob, Project, Subtask
from core.pr_merger import PrMergeError


@pytest.fixture
def session_factory(tmp_path, monkeypatch):
    engine = make_engine(str(tmp_path / "test.db"))
    init_db(bind=engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(subtasks, "SessionLocal", factory)
    with factory() as session:
        session.add(
            Project(name="p", github_repo="owner/repo", repo_path="repo", default_branch="master")
        )
        session.commit()
    return factory


@pytest.fixture
def merge_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(subtasks, "merge_pr_with_update", lambda *args: calls.append(args))
    return calls


def _add_subtask(factory, state, pr_number=7, job_status=None) -> int:
    with factory() as session:
        subtask = Subtask(
            project_id=1,
            github_issue_number=5,
            title="t",
            instruction="",
            branch_name="issue-5-x-1",
            github_pr_number=pr_number,
            lifecycle_state=state,
        )
        session.add(subtask)
        session.flush()
        if job_status:
            session.add(ExecutionJob(subtask_id=subtask.id, status=job_status))
        session.commit()
        return subtask.id


def _state_of(factory, subtask_id) -> str:
    with factory() as session:
        return session.get(Subtask, subtask_id).lifecycle_state


def test_merge_subtask_merges_pr(session_factory, merge_calls):
    subtask_id = _add_subtask(session_factory, "resolved", job_status="succeeded")

    result = subtasks.merge_subtask(subtask_id)

    assert len(merge_calls) == 1
    repo, repo_path, _, pr = merge_calls[0]
    assert (repo, repo_path) == ("owner/repo", "repo")
    assert pr == {"number": 7, "headRefName": "issue-5-x-1", "baseRefName": "master"}
    assert result["lifecycle_state"] == "merged"
    assert _state_of(session_factory, subtask_id) == "merged"


@pytest.mark.parametrize("state", ["draft", "merged", "canceled"])
def test_merge_subtask_rejects_not_resolved(session_factory, merge_calls, state):
    subtask_id = _add_subtask(session_factory, state)

    with pytest.raises(HTTPException) as exc:
        subtasks.merge_subtask(subtask_id)

    assert exc.value.status_code == 409
    assert merge_calls == []


def test_merge_subtask_rejects_without_pr(session_factory, merge_calls):
    subtask_id = _add_subtask(session_factory, "resolved", pr_number=None)

    with pytest.raises(HTTPException) as exc:
        subtasks.merge_subtask(subtask_id)

    assert exc.value.status_code == 409
    assert merge_calls == []


@pytest.mark.parametrize("job_status", ["queued", "running"])
def test_merge_subtask_rejects_while_job_active(session_factory, merge_calls, job_status):
    subtask_id = _add_subtask(session_factory, "resolved", job_status=job_status)

    with pytest.raises(HTTPException) as exc:
        subtasks.merge_subtask(subtask_id)

    assert exc.value.status_code == 409
    assert merge_calls == []


def test_merge_subtask_keeps_state_on_failure(session_factory, monkeypatch):
    subtask_id = _add_subtask(session_factory, "resolved")

    def fail(*args):
        raise PrMergeError("conflict")

    monkeypatch.setattr(subtasks, "merge_pr_with_update", fail)

    with pytest.raises(HTTPException) as exc:
        subtasks.merge_subtask(subtask_id)

    assert exc.value.status_code == 500
    assert _state_of(session_factory, subtask_id) == "resolved"
