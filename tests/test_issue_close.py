import subprocess

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker

from app.routes import projects
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
    with factory() as session:
        session.add(
            Project(name="p", github_repo="owner/repo", repo_path="x", default_branch="master")
        )
        session.commit()
    return factory


def _add_subtask(factory, state, issue_number=5):
    with factory() as session:
        session.add(
            Subtask(
                project_id=1,
                github_issue_number=issue_number,
                title="t",
                instruction="",
                branch_name=f"issue-{issue_number}-{state}",
                lifecycle_state=state,
            )
        )
        session.commit()


def test_close_issue_runs_gh_issue_close(monkeypatch):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(github_client.subprocess, "run", run)

    github_client.close_issue("owner/repo", 12)

    assert calls == [["gh", "issue", "close", "12", "--repo", "owner/repo"]]


@pytest.mark.parametrize("states", [[], ["merged"], ["merged", "canceled"]])
def test_close_issue_route_closes_when_no_unresolved_mr(session_factory, monkeypatch, states):
    for state in states:
        _add_subtask(session_factory, state)
    _add_subtask(session_factory, "draft", issue_number=6)
    calls = []
    monkeypatch.setattr(projects, "close_issue", lambda *args: calls.append(args))

    result = projects.close_project_issue(1, 5)

    assert calls == [("owner/repo", 5)]
    assert result == {"number": 5, "state": "CLOSED"}


@pytest.mark.parametrize("state", ["draft", "resolved"])
def test_close_issue_route_rejects_unresolved_mr(session_factory, monkeypatch, state):
    _add_subtask(session_factory, "merged")
    _add_subtask(session_factory, state)
    calls = []
    monkeypatch.setattr(projects, "close_issue", lambda *args: calls.append(args))

    with pytest.raises(HTTPException) as exc:
        projects.close_project_issue(1, 5)

    assert exc.value.status_code == 409
    assert calls == []


def test_close_issue_route_reports_gh_failure(session_factory, monkeypatch):
    def fail(*args):
        raise GitHubClientError("boom")

    monkeypatch.setattr(projects, "close_issue", fail)

    with pytest.raises(HTTPException) as exc:
        projects.close_project_issue(1, 5)
    assert exc.value.status_code == 500
