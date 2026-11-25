import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy.orm import sessionmaker

from app.routes import subtasks
from core.db import init_db, make_engine
from core import issue_mr_creation as creation
from core.github_client import GitHubClientError
from core.models import Project, Subtask


@pytest.fixture
def session_factory(tmp_path, monkeypatch):
    engine = make_engine(str(tmp_path / "test.db"))
    init_db(bind=engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(subtasks, "SessionLocal", factory)
    with factory() as session:
        session.add(
            Project(id=1, name="p", github_repo="owner/repo", repo_path="x", default_branch="master")
        )
        session.commit()
    return factory


@pytest.fixture
def pushed(monkeypatch):
    calls = []

    def fake_push(project, branch_name, title, instruction, body):
        calls.append({"branch_name": branch_name, "title": title, "body": body})
        return {"number": 21, "url": "u"}

    monkeypatch.setattr(creation, "_push_draft_pr", fake_push)
    return calls


def _link_request(branch_name="issue-new-abcd1234-subtask-1"):
    return subtasks.LinkPendingSubtaskRequest(
        project_id=1,
        github_issue_number=7,
        title="あいうえおー①",
        branch_name=branch_name,
        github_pr_number=21,
        pr_url="u",
    )


def test_create_pending_subtask_creates_unlinked_pr(session_factory, pushed):
    result = subtasks.create_pending_subtask(
        subtasks.CreatePendingSubtaskRequest(project_id=1, issue_title=" あいうえお ")
    )

    assert result["title"] == "あいうえおー①"
    assert result["branch_name"].startswith("issue-new-")
    assert result["github_pr_number"] == 21
    assert pushed[0]["body"] == creation.PENDING_PR_BODY
    with session_factory() as session:
        assert session.query(Subtask).count() == 0


def test_create_pending_subtask_branch_names_are_unique(session_factory, pushed):
    request = subtasks.CreatePendingSubtaskRequest(project_id=1, issue_title="あ")

    subtasks.create_pending_subtask(request)
    subtasks.create_pending_subtask(request)

    assert pushed[0]["branch_name"] != pushed[1]["branch_name"]


def test_create_pending_subtask_with_blank_title_is_bad_request(session_factory, pushed):
    with pytest.raises(HTTPException) as exc:
        subtasks.create_pending_subtask(
            subtasks.CreatePendingSubtaskRequest(project_id=1, issue_title="  ")
        )

    assert exc.value.status_code == 400
    assert pushed == []


def test_link_pending_subtask_registers_row_and_links_after_response(session_factory, monkeypatch):
    edits = []
    monkeypatch.setattr(creation, "edit_pr_body", lambda *args: edits.append(args))
    background = BackgroundTasks()

    result = subtasks.link_pending_subtask(_link_request(), background)

    with session_factory() as session:
        row = session.get(Subtask, result["id"])
        assert (row.github_issue_number, row.github_pr_number, row.lifecycle_state) == (7, 21, "draft")
    assert edits == []
    for task in background.tasks:
        task.func(*task.args, **task.kwargs)
    assert edits == [("owner/repo", 21, "Related to #7")]


def test_link_pending_subtask_rejects_linked_branch(session_factory):
    with pytest.raises(HTTPException) as exc:
        subtasks.link_pending_subtask(_link_request("issue-7-subtask-1"), BackgroundTasks())

    assert exc.value.status_code == 400


def test_link_pr_to_issue_ignores_github_error(monkeypatch):
    def fail(*args):
        raise GitHubClientError("boom")

    monkeypatch.setattr(creation, "edit_pr_body", fail)

    creation.link_pr_to_issue("owner/repo", 21, 7)


def test_discard_pending_subtask_closes_pr(session_factory, monkeypatch):
    closed = []
    monkeypatch.setattr(creation, "close_pr", lambda *args: closed.append(args))

    subtasks.discard_pending_subtask(
        subtasks.DiscardPendingSubtaskRequest(project_id=1, github_pr_number=21)
    )

    assert closed == [("owner/repo", 21)]
