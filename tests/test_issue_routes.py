import pytest
from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker

from app.routes import projects
from core.db import init_db, make_engine
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


def _capture_list_issues(monkeypatch):
    calls = []

    def fake(repo, state):
        calls.append((repo, state))
        return []

    monkeypatch.setattr(projects, "list_issues", fake)
    return calls


def test_get_projects_includes_repo_display_info(session_factory):
    [project] = projects.get_projects()

    assert (project["repo_number"], project["display_name"], project["repo_url"]) == (
        None,
        "p",
        "https://github.com/owner/repo",
    )


def test_get_issues_passes_state(session_factory, monkeypatch):
    calls = _capture_list_issues(monkeypatch)

    projects.get_issues(1, "closed")

    assert calls == [("owner/repo", "closed")]


def test_get_issues_defaults_to_open(session_factory, monkeypatch):
    calls = _capture_list_issues(monkeypatch)

    projects.get_issues(1)

    assert calls == [("owner/repo", "open")]


def test_get_issue_subtasks_returns_db_states(session_factory):
    with session_factory() as session:
        session.add(
            Subtask(
                project_id=1,
                github_issue_number=5,
                title="t",
                instruction="",
                branch_name="b",
                github_pr_number=9,
                lifecycle_state="in_review",
            )
        )
        session.commit()

    subtasks = projects.get_issue_subtasks(1, 5)

    assert [(s["lifecycle_state"], s["pr_url"]) for s in subtasks] == [
        ("in_review", "https://github.com/owner/repo/pull/9")
    ]


def test_get_issue_subtasks_unknown_project(session_factory):
    with pytest.raises(HTTPException) as error:
        projects.get_issue_subtasks(99, 5)
    assert error.value.status_code == 404
