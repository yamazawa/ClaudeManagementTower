import pytest
from sqlalchemy.orm import sessionmaker

from app.routes import projects
from core.db import init_db, make_engine
from core.models import Project


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


def test_get_issues_passes_state(session_factory, monkeypatch):
    calls = _capture_list_issues(monkeypatch)

    projects.get_issues(1, "closed")

    assert calls == [("owner/repo", "closed")]


def test_get_issues_defaults_to_open(session_factory, monkeypatch):
    calls = _capture_list_issues(monkeypatch)

    projects.get_issues(1)

    assert calls == [("owner/repo", "open")]
