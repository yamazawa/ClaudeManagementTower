import pytest
from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker

from app.routes import merges, subtasks
from core import merge_queue
from core.db import init_db, make_engine
from core.models import ExecutionJob, MergeJob, Project, Subtask
from core.pr_merger import PrMergeError


@pytest.fixture
def session_factory(tmp_path, monkeypatch):
    engine = make_engine(str(tmp_path / "test.db"))
    init_db(bind=engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(subtasks, "SessionLocal", factory)
    monkeypatch.setattr(merges, "SessionLocal", factory)
    with factory() as session:
        session.add(
            Project(name="p", github_repo="owner/repo", repo_path="repo", default_branch="master")
        )
        session.commit()
    return factory


@pytest.fixture
def merge_calls():
    return []


def _fail_merge(*args):
    raise PrMergeError("conflict")


def _add_subtask(factory, state, pr_number=7, job_status=None, branch="issue-5-x-1") -> int:
    with factory() as session:
        subtask = Subtask(
            project_id=1,
            github_issue_number=5,
            title="t",
            instruction="",
            branch_name=branch,
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


def _merge_statuses(factory) -> list[str]:
    with factory() as session:
        return [j.status for j in session.query(MergeJob).order_by(MergeJob.id)]


def _process(factory, calls) -> bool:
    return merge_queue.process_next_merge(factory, lambda *args: calls.append(args))


def test_merge_subtask_enqueues_without_merging(session_factory, merge_calls):
    subtask_id = _add_subtask(session_factory, "resolved", job_status="succeeded")

    result = subtasks.merge_subtask(subtask_id)

    assert result["lifecycle_state"] == "resolved"
    assert result["latest_merge"]["status"] == "queued"
    assert _merge_statuses(session_factory) == ["queued"]
    assert merge_calls == []


def test_process_next_merge_merges_pr(session_factory, merge_calls):
    subtask_id = _add_subtask(session_factory, "resolved")
    subtasks.merge_subtask(subtask_id)

    assert _process(session_factory, merge_calls) is True

    repo, repo_path, _, pr = merge_calls[0]
    assert (repo, repo_path) == ("owner/repo", "repo")
    assert pr == {"number": 7, "headRefName": "issue-5-x-1", "baseRefName": "master"}
    assert _state_of(session_factory, subtask_id) == "merged"
    assert _merge_statuses(session_factory) == ["succeeded"]


def test_process_next_merge_handles_one_job_at_a_time_in_order(session_factory, merge_calls):
    first = _add_subtask(session_factory, "resolved", pr_number=7, branch="a")
    second = _add_subtask(session_factory, "resolved", pr_number=8, branch="b")
    subtasks.merge_subtask(second)
    subtasks.merge_subtask(first)

    _process(session_factory, merge_calls)

    assert [c[3]["number"] for c in merge_calls] == [8]
    assert _merge_statuses(session_factory) == ["succeeded", "queued"]

    _process(session_factory, merge_calls)

    assert [c[3]["number"] for c in merge_calls] == [8, 7]
    assert _process(session_factory, merge_calls) is False


def test_process_next_merge_records_failure_and_keeps_state(session_factory):
    subtask_id = _add_subtask(session_factory, "resolved")
    subtasks.merge_subtask(subtask_id)

    merge_queue.process_next_merge(session_factory, _fail_merge)

    assert _state_of(session_factory, subtask_id) == "resolved"
    with session_factory() as session:
        job = session.query(MergeJob).one()
        assert (job.status, job.error_message) == ("failed", "conflict")


def test_merge_subtask_rejects_already_queued(session_factory, merge_calls):
    subtask_id = _add_subtask(session_factory, "resolved")
    subtasks.merge_subtask(subtask_id)

    with pytest.raises(HTTPException) as exc:
        subtasks.merge_subtask(subtask_id)

    assert exc.value.status_code == 409
    assert _merge_statuses(session_factory) == ["queued"]


def test_merge_subtask_allows_retry_after_failure(session_factory):
    subtask_id = _add_subtask(session_factory, "resolved")
    subtasks.merge_subtask(subtask_id)
    merge_queue.process_next_merge(session_factory, _fail_merge)

    subtasks.merge_subtask(subtask_id)

    assert _merge_statuses(session_factory) == ["failed", "queued"]


@pytest.mark.parametrize("state", ["draft", "merged", "canceled"])
def test_merge_subtask_rejects_not_resolved(session_factory, state):
    subtask_id = _add_subtask(session_factory, state)

    with pytest.raises(HTTPException) as exc:
        subtasks.merge_subtask(subtask_id)

    assert exc.value.status_code == 409
    assert _merge_statuses(session_factory) == []


def test_merge_subtask_rejects_without_pr(session_factory):
    subtask_id = _add_subtask(session_factory, "resolved", pr_number=None)

    with pytest.raises(HTTPException) as exc:
        subtasks.merge_subtask(subtask_id)

    assert exc.value.status_code == 409
    assert _merge_statuses(session_factory) == []


@pytest.mark.parametrize("job_status", ["queued", "running"])
def test_merge_subtask_rejects_while_job_active(session_factory, job_status):
    subtask_id = _add_subtask(session_factory, "resolved", job_status=job_status)

    with pytest.raises(HTTPException) as exc:
        subtasks.merge_subtask(subtask_id)

    assert exc.value.status_code == 409
    assert _merge_statuses(session_factory) == []


def test_execute_subtask_rejects_while_merge_queued(session_factory):
    subtask_id = _add_subtask(session_factory, "resolved")
    subtasks.merge_subtask(subtask_id)

    with pytest.raises(HTTPException) as exc:
        subtasks.execute_subtask(subtask_id)

    assert exc.value.status_code == 409


def test_get_merges_lists_running_and_queued_in_order(session_factory, merge_calls):
    first = _add_subtask(session_factory, "resolved", pr_number=7, branch="a")
    second = _add_subtask(session_factory, "resolved", pr_number=8, branch="b")
    done = _add_subtask(session_factory, "resolved", pr_number=9, branch="c")
    subtasks.merge_subtask(done)
    _process(session_factory, merge_calls)
    subtasks.merge_subtask(first)
    subtasks.merge_subtask(second)
    with session_factory() as session:
        merge_queue._claim_next(session)

    result = merges.get_merges()

    assert [(m["github_pr_number"], m["status"]) for m in result] == [(7, "running"), (8, "queued")]


def test_recover_interrupted_merges_marks_running_failed(session_factory):
    subtask_id = _add_subtask(session_factory, "resolved")
    subtasks.merge_subtask(subtask_id)
    with session_factory() as session:
        merge_queue._claim_next(session)

    merge_queue.recover_interrupted_merges(session_factory)

    assert _merge_statuses(session_factory) == ["failed"]
