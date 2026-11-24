import pytest
from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker

from app.routes import subtasks
from app.routes.lookups import get_project_or_404, get_subtask_and_project_or_404, get_subtask_or_404
from core.db import init_db, make_engine
from core.models import Project, Subtask


@pytest.fixture
def factory(tmp_path, monkeypatch):
    """プロジェクト1件と、そのサブタスク・所属プロジェクトが無いサブタスクを保存する"""
    engine = make_engine(str(tmp_path / "test.db"))
    init_db(bind=engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        session.add(Project(id=1, name="p", github_repo="owner/repo", repo_path="x", default_branch="master"))
        session.add(_subtask(1, project_id=1))
        session.add(_subtask(2, project_id=99))
        session.commit()
    monkeypatch.setattr(subtasks, "SessionLocal", factory)
    return factory


def _subtask(subtask_id: int, project_id: int) -> Subtask:
    return Subtask(
        id=subtask_id,
        project_id=project_id,
        github_issue_number=5,
        title="t",
        instruction="",
        branch_name=f"issue-5-{subtask_id}",
        lifecycle_state="draft",
    )


def _status_of(func, *args) -> int:
    with pytest.raises(HTTPException) as error:
        func(*args)
    return error.value.status_code


def test_get_project_or_404(factory):
    with factory() as session:
        assert get_project_or_404(session, 1).github_repo == "owner/repo"
        assert _status_of(get_project_or_404, session, 99) == 404


def test_get_subtask_or_404(factory):
    with factory() as session:
        assert get_subtask_or_404(session, 1).id == 1
        assert _status_of(get_subtask_or_404, session, 99) == 404


def test_get_subtask_and_project_or_404_rejects_missing_project(factory):
    with factory() as session:
        subtask, project = get_subtask_and_project_or_404(session, 1)
        assert (subtask.id, project.id) == (1, 1)
        assert _status_of(get_subtask_and_project_or_404, session, 2) == 404


def test_close_subtask_of_deleted_project_returns_404(factory):
    assert _status_of(subtasks.close_subtask, 2) == 404
