import asyncio
import io

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import sessionmaker

from app.routes import subtasks
from core.db import init_db, make_engine
from core.models import Project, Subtask


@pytest.fixture
def session_factory(tmp_path, monkeypatch):
    engine = make_engine(str(tmp_path / "test.db"))
    init_db(bind=engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(subtasks, "SessionLocal", factory)
    with factory() as session:
        session.add(_project())
        session.commit()
    return factory


@pytest.fixture
def created(monkeypatch):
    calls = []

    def fake_create(project, issue_number, title, instruction, slug_suffix, slug_source=None):
        calls.append({"title": title, "slug_source": slug_source})
        return f"issue-{issue_number}-{slug_suffix}", {"number": 10 + slug_suffix, "url": "u"}

    monkeypatch.setattr(subtasks, "_create_branch_and_draft_pr", fake_create)
    monkeypatch.setattr(subtasks, "get_issue", lambda repo, number: {"title": "あいうえお"})
    return calls


def _create(title):
    return subtasks.create_subtask(
        subtasks.CreateSubtaskRequest(project_id=1, github_issue_number=5, title=title)
    )


def test_create_subtask_composes_issue_title(session_factory, created):
    result = _create("かきくけこ")

    assert result["title"] == "あいうえおーかきくけこ"
    assert created[0]["slug_source"] == "かきくけこ"


def test_create_subtask_with_blank_title_uses_free_number(session_factory, created):
    with session_factory() as session:
        session.add(
            Subtask(
                project_id=1,
                github_issue_number=5,
                title="あいうえおー①",
                instruction="",
                branch_name="issue-5-x",
                lifecycle_state="draft",
            )
        )
        session.commit()

    result = _create("  ")

    assert result["title"] == "あいうえおー②"


def test_create_subtask_adopts_row_imported_by_sync(session_factory, monkeypatch):
    def fake_create(project, issue_number, title, instruction, slug_suffix, slug_source=None):
        # PR作成直後に自動同期が取り込んだ状態を再現する
        with session_factory() as session:
            session.add(
                Subtask(
                    project_id=1,
                    github_issue_number=issue_number,
                    title="PR title",
                    instruction="",
                    branch_name="issue-5-x",
                    github_pr_number=11,
                    lifecycle_state="draft",
                )
            )
            session.commit()
        return "issue-5-x", {"number": 11, "url": "u"}

    monkeypatch.setattr(subtasks, "_create_branch_and_draft_pr", fake_create)
    monkeypatch.setattr(subtasks, "get_issue", lambda repo, number: {"title": "あいうえお"})

    result = _create("かきくけこ")

    with session_factory() as session:
        rows = session.query(Subtask).all()
    assert [(s.id, s.title) for s in rows] == [(result["id"], "あいうえおーかきくけこ")]


def _project():
    return Project(id=1, name="p", github_repo="owner/repo", repo_path="x", default_branch="master")


def test_branch_name_unique_for_same_title(monkeypatch):
    monkeypatch.setattr(subtasks, "create_worktree", lambda *a, **k: None)
    monkeypatch.setattr(subtasks, "commit_subtask_instruction", lambda *a, **k: None)
    monkeypatch.setattr(subtasks, "push_branch", lambda *a, **k: None)
    monkeypatch.setattr(subtasks, "create_draft_pr", lambda **k: {"number": 1, "url": "u"})

    branch_1, _ = subtasks._create_branch_and_draft_pr(_project(), 53, "MR一覧の項目編集", "", 1)
    branch_2, _ = subtasks._create_branch_and_draft_pr(_project(), 53, "MR内容のレイアウト編集", "", 2)

    assert branch_1 != branch_2


def _add_subtask(session_factory):
    with session_factory() as session:
        session.add(
            Subtask(
                project_id=1,
                github_issue_number=5,
                title="t",
                instruction="",
                branch_name="issue-5-x",
                lifecycle_state="draft",
            )
        )
        session.commit()


def _upload(subtask_id, filename, data):
    file = UploadFile(file=io.BytesIO(data), filename=filename)
    return asyncio.run(subtasks.upload_attachment(subtask_id, file))


def test_upload_attachment_saves_into_worktree(session_factory, tmp_path, monkeypatch):
    monkeypatch.setattr(subtasks.settings, "worktree_base_dir", str(tmp_path))
    (tmp_path / "issue-5-x").mkdir()
    _add_subtask(session_factory)

    first = _upload(1, "a.png", b"1")
    second = _upload(1, "b.txt", b"2")

    assert [first["id"], second["id"]] == ["S1", "S2"]
    assert [a["filename"] for a in subtasks.get_attachments(1)] == ["a.png", "b.txt"]


def test_upload_attachment_without_worktree_is_conflict(session_factory, tmp_path, monkeypatch):
    monkeypatch.setattr(subtasks.settings, "worktree_base_dir", str(tmp_path))
    _add_subtask(session_factory)

    with pytest.raises(HTTPException) as exc:
        _upload(1, "a.png", b"1")

    assert exc.value.status_code == 409


def test_get_attachments_unknown_subtask_is_not_found(session_factory):
    with pytest.raises(HTTPException) as exc:
        subtasks.get_attachments(999)

    assert exc.value.status_code == 404


def test_get_attachment_file_returns_saved_file(session_factory, tmp_path, monkeypatch):
    monkeypatch.setattr(subtasks.settings, "worktree_base_dir", str(tmp_path))
    (tmp_path / "issue-5-x").mkdir()
    _add_subtask(session_factory)
    _upload(1, "a.png", b"1")

    response = subtasks.get_attachment_file(1, "S1")

    assert str(response.path).endswith("a.png")


def test_get_attachment_file_unknown_id_is_not_found(session_factory, tmp_path, monkeypatch):
    monkeypatch.setattr(subtasks.settings, "worktree_base_dir", str(tmp_path))
    (tmp_path / "issue-5-x").mkdir()
    _add_subtask(session_factory)

    with pytest.raises(HTTPException) as exc:
        subtasks.get_attachment_file(1, "S1")

    assert exc.value.status_code == 404


def test_remove_attachment_deletes_saved_file(session_factory, tmp_path, monkeypatch):
    monkeypatch.setattr(subtasks.settings, "worktree_base_dir", str(tmp_path))
    (tmp_path / "issue-5-x").mkdir()
    _add_subtask(session_factory)
    _upload(1, "a.png", b"1")
    _upload(1, "b.txt", b"2")

    assert subtasks.remove_attachment(1, "S1") == {"id": "S1"}

    assert [a["id"] for a in subtasks.get_attachments(1)] == ["S2"]


def test_remove_attachment_unknown_id_is_not_found(session_factory, tmp_path, monkeypatch):
    monkeypatch.setattr(subtasks.settings, "worktree_base_dir", str(tmp_path))
    (tmp_path / "issue-5-x").mkdir()
    _add_subtask(session_factory)

    with pytest.raises(HTTPException) as exc:
        subtasks.remove_attachment(1, "S1")

    assert exc.value.status_code == 404
