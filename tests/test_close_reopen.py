import subprocess

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker

from app.routes import projects, subtasks
from core import github_client
from core.db import init_db, make_engine
from core.github_client import GitHubClientError
from core.models import Project, Subtask


@pytest.fixture
def session_factory(tmp_path, monkeypatch):
    engine = make_engine(str(tmp_path / "test.db"))
    init_db(bind=engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(projects, "SessionLocal", factory)
    monkeypatch.setattr(subtasks, "SessionLocal", factory)
    with factory() as session:
        session.add(
            Project(name="p", github_repo="owner/repo", repo_path="x", default_branch="master")
        )
        session.commit()
    return factory


def _add_subtask(factory, state, pr_number=7) -> int:
    with factory() as session:
        subtask = Subtask(
            project_id=1,
            github_issue_number=5,
            title="t",
            instruction="",
            branch_name=f"issue-5-{state}",
            github_pr_number=pr_number,
            lifecycle_state=state,
        )
        session.add(subtask)
        session.commit()
        return subtask.id


def _state_of(factory, subtask_id) -> str:
    with factory() as session:
        return session.get(Subtask, subtask_id).lifecycle_state


@pytest.mark.parametrize(
    ("func", "expected"),
    [
        (lambda: github_client.reopen_issue("owner/repo", 3), ["issue", "reopen", "3"]),
        (lambda: github_client.close_pr("owner/repo", 4), ["pr", "close", "4"]),
        (lambda: github_client.reopen_pr("owner/repo", 4), ["pr", "reopen", "4"]),
    ],
)
def test_gh_commands(monkeypatch, func, expected):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(github_client.subprocess, "run", run)

    func()

    assert calls == [["gh", *expected, "--repo", "owner/repo"]]


def test_reopen_issue_route(session_factory, monkeypatch):
    calls = []
    monkeypatch.setattr(projects, "reopen_issue", lambda *args: calls.append(args))

    result = projects.reopen_project_issue(1, 5)

    assert calls == [("owner/repo", 5)]
    assert result == {"number": 5, "state": "OPEN"}


def test_reopen_issue_route_reports_gh_failure(session_factory, monkeypatch):
    def fail(*args):
        raise GitHubClientError("boom")

    monkeypatch.setattr(projects, "reopen_issue", fail)

    with pytest.raises(HTTPException) as exc:
        projects.reopen_project_issue(1, 5)
    assert exc.value.status_code == 500


@pytest.mark.parametrize("state", ["draft", "resolved"])
def test_close_subtask_closes_pr(session_factory, monkeypatch, state):
    subtask_id = _add_subtask(session_factory, state)
    calls = []
    monkeypatch.setattr(subtasks, "close_pr", lambda *args: calls.append(args))

    result = subtasks.close_subtask(subtask_id)

    assert calls == [("owner/repo", 7)]
    assert result["lifecycle_state"] == "canceled"
    assert _state_of(session_factory, subtask_id) == "canceled"


@pytest.mark.parametrize("state", ["merged", "canceled"])
def test_close_subtask_rejects_resolved(session_factory, monkeypatch, state):
    subtask_id = _add_subtask(session_factory, state)
    calls = []
    monkeypatch.setattr(subtasks, "close_pr", lambda *args: calls.append(args))

    with pytest.raises(HTTPException) as exc:
        subtasks.close_subtask(subtask_id)

    assert exc.value.status_code == 409
    assert calls == []


def test_close_subtask_keeps_state_on_gh_failure(session_factory, monkeypatch):
    subtask_id = _add_subtask(session_factory, "draft")

    def fail(*args):
        raise GitHubClientError("boom")

    monkeypatch.setattr(subtasks, "close_pr", fail)

    with pytest.raises(HTTPException) as exc:
        subtasks.close_subtask(subtask_id)

    assert exc.value.status_code == 500
    assert _state_of(session_factory, subtask_id) == "draft"


@pytest.mark.parametrize(("is_draft", "expected"), [(True, "draft"), (False, "resolved")])
def test_reopen_subtask_restores_state_from_pr(session_factory, monkeypatch, is_draft, expected):
    subtask_id = _add_subtask(session_factory, "canceled")
    calls = []
    monkeypatch.setattr(subtasks, "reopen_pr", lambda *args: calls.append(args))
    monkeypatch.setattr(
        subtasks,
        "get_pr_state",
        lambda *args: {"number": 7, "isDraft": is_draft, "state": "OPEN", "mergedAt": None},
    )

    result = subtasks.reopen_subtask(subtask_id)

    assert calls == [("owner/repo", 7)]
    assert result["lifecycle_state"] == expected
    assert _state_of(session_factory, subtask_id) == expected


def test_reopen_subtask_without_pr_becomes_draft(session_factory, monkeypatch):
    subtask_id = _add_subtask(session_factory, "canceled", pr_number=None)

    result = subtasks.reopen_subtask(subtask_id)

    assert result["lifecycle_state"] == "draft"


@pytest.mark.parametrize("state", ["draft", "resolved", "merged"])
def test_reopen_subtask_rejects_not_closed(session_factory, state):
    subtask_id = _add_subtask(session_factory, state)

    with pytest.raises(HTTPException) as exc:
        subtasks.reopen_subtask(subtask_id)

    assert exc.value.status_code == 409


def test_reopen_subtask_keeps_state_on_gh_failure(session_factory, monkeypatch):
    subtask_id = _add_subtask(session_factory, "canceled")

    def fail(*args):
        raise GitHubClientError("boom")

    monkeypatch.setattr(subtasks, "reopen_pr", fail)

    with pytest.raises(HTTPException) as exc:
        subtasks.reopen_subtask(subtask_id)

    assert exc.value.status_code == 500
    assert _state_of(session_factory, subtask_id) == "canceled"
