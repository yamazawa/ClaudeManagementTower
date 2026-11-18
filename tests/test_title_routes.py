import pytest
from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker

from app.routes import projects, subtasks
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
    monkeypatch.setattr(subtasks, "get_issue", lambda repo, number: {"title": "親"})
    with factory() as session:
        session.add(
            Project(name="p", github_repo="owner/repo", repo_path="x", default_branch="master")
        )
        session.commit()
    return factory


def _add_subtask(factory, pr_number, title="旧タイトル"):
    with factory() as session:
        subtask = Subtask(
            project_id=1,
            github_issue_number=5,
            title=title,
            instruction="",
            branch_name="issue-5-old",
            github_pr_number=pr_number,
            lifecycle_state="draft",
        )
        session.add(subtask)
        session.commit()
        return subtask.id


def test_update_issue_title_calls_gh(session_factory, monkeypatch):
    calls = []
    monkeypatch.setattr(projects, "edit_issue_title", lambda *args: calls.append(args))

    result = projects.update_issue_title(1, 5, projects.UpdateTitleRequest(title=" 新 "))

    assert calls == [("owner/repo", 5, "新")]
    assert result == {"number": 5, "title": "新"}


def test_update_issue_title_rejects_empty(session_factory):
    with pytest.raises(HTTPException) as exc:
        projects.update_issue_title(1, 5, projects.UpdateTitleRequest(title="  "))
    assert exc.value.status_code == 400


def test_update_subtask_title_updates_pr_and_db(session_factory, monkeypatch):
    subtask_id = _add_subtask(session_factory, pr_number=9)
    calls = []
    monkeypatch.setattr(subtasks, "edit_pr_title", lambda *args: calls.append(args))

    subtasks.update_subtask_title(subtask_id, subtasks.UpdateSubtaskTitleRequest(title="新"))

    assert calls == [("owner/repo", 9, "親ー新")]
    with session_factory() as session:
        reloaded = session.get(Subtask, subtask_id)
        assert reloaded.title == "親ー新"
        assert reloaded.branch_name == "issue-5-old"


def test_update_subtask_title_keeps_db_when_gh_fails(session_factory, monkeypatch):
    subtask_id = _add_subtask(session_factory, pr_number=9)

    def fail(*args):
        raise GitHubClientError("boom")

    monkeypatch.setattr(subtasks, "edit_pr_title", fail)

    with pytest.raises(HTTPException) as exc:
        subtasks.update_subtask_title(subtask_id, subtasks.UpdateSubtaskTitleRequest(title="新"))
    assert exc.value.status_code == 500
    with session_factory() as session:
        assert session.get(Subtask, subtask_id).title == "旧タイトル"


def test_update_subtask_title_without_pr_updates_db_only(session_factory, monkeypatch):
    subtask_id = _add_subtask(session_factory, pr_number=None)
    calls = []
    monkeypatch.setattr(subtasks, "edit_pr_title", lambda *args: calls.append(args))

    subtasks.update_subtask_title(subtask_id, subtasks.UpdateSubtaskTitleRequest(title="新"))

    assert calls == []
    with session_factory() as session:
        assert session.get(Subtask, subtask_id).title == "親ー新"
