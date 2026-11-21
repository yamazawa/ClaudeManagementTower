import pytest
from sqlalchemy.orm import sessionmaker

from app.routes import mr_statuses
from core import deploy
from core.db import init_db, make_engine
from core.models import ExecutionJob, MergeJob, Project, Subtask


@pytest.fixture
def session_factory(tmp_path, monkeypatch):
    engine = make_engine(str(tmp_path / "test.db"))
    init_db(bind=engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(mr_statuses, "SessionLocal", factory)
    monkeypatch.setattr(deploy, "_running_project_ids", set())
    with factory() as session:
        session.add_all(
            Project(name=f"p{i}", github_repo=f"owner/r{i}", repo_path="x", default_branch="master")
            for i in (1, 2)
        )
        session.commit()
    return factory


def _add(factory, project_id, issue, state, jobs=(), merges=()):
    with factory() as session:
        subtask = Subtask(
            project_id=project_id,
            github_issue_number=issue,
            title="t",
            instruction="",
            branch_name=f"b-{project_id}-{issue}-{state}-{len(jobs)}-{len(merges)}",
            lifecycle_state=state,
        )
        session.add(subtask)
        session.flush()
        session.add_all(ExecutionJob(subtask_id=subtask.id, status=s) for s in jobs)
        session.add_all(MergeJob(subtask_id=subtask.id, status=s) for s in merges)
        session.commit()


def test_counts_all_projects_by_derived_status(session_factory):
    _add(session_factory, 1, 10, "draft")
    _add(session_factory, 1, 10, "draft", jobs=("succeeded", "running"))
    _add(session_factory, 1, 11, "resolved", merges=("failed", "queued"))
    _add(session_factory, 2, 20, "resolved", jobs=("running", "succeeded"))
    _add(session_factory, 2, 20, "merged")
    _add(session_factory, 2, 21, "deployed")
    _add(session_factory, 2, 21, "canceled")

    result = mr_statuses.get_mr_statuses()

    assert result["counts"] == {
        "draft": 1,
        "resolving": 1,
        "resolved": 1,
        "merging": 1,
        "merged": 1,
        "deploying": 0,
        "deployed": 1,
    }
    assert result["projects"] == {
        1: {10: ["draft", "resolving"], 11: ["merging"]},
        2: {20: ["merged", "resolved"], 21: ["deployed"]},
    }


def test_merged_in_deploying_project_is_deploying(session_factory, monkeypatch):
    monkeypatch.setattr(deploy, "_running_project_ids", {2})
    _add(session_factory, 1, 10, "merged")
    _add(session_factory, 2, 20, "merged")

    result = mr_statuses.get_mr_statuses()

    assert (result["counts"]["merged"], result["counts"]["deploying"]) == (1, 1)
    assert result["projects"][2] == {20: ["deploying"]}


def test_no_subtasks_returns_zero_counts(session_factory):
    result = mr_statuses.get_mr_statuses()

    assert set(result["counts"].values()) == {0}
    assert result["projects"] == {}
