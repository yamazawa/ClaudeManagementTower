import pytest
from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker

from app.routes import ideas
from core import idea_approval
from core.db import init_db, make_engine
from core.github_client import GitHubClientError
from core.idea_queue import IdeaJobAlreadyActive, IdeaProjectNotFound
from core.ideas import IdeaAlreadyDecided, IdeaNotFound, IdeaStatus, list_ideas, save_proposals
from core.models import IdeaJob, Project


def _raiser(exc):
    def fail(*args, **kwargs):
        raise exc

    return fail


@pytest.mark.parametrize(("exc", "status"), [(IdeaProjectNotFound("x"), 404), (IdeaJobAlreadyActive("x"), 409)])
def test_run_maps_errors(monkeypatch, exc, status):
    monkeypatch.setattr(ideas, "enqueue_idea_job", _raiser(exc))

    with pytest.raises(HTTPException) as error:
        ideas.run_idea_generation(1)
    assert error.value.status_code == status


def test_run_returns_queued_job(monkeypatch):
    monkeypatch.setattr(ideas, "enqueue_idea_job", lambda project_id: {"id": 4, "project_id": project_id})

    assert ideas.run_idea_generation(2) == {"id": 4, "project_id": 2}


@pytest.mark.parametrize(
    ("tab", "statuses"),
    [("pending", IdeaStatus.PENDING_STATES), ("rejected", IdeaStatus.REJECTED_STATES), ("all", None)],
)
def test_get_ideas_filters_by_tab(monkeypatch, tab, statuses):
    calls = []
    monkeypatch.setattr(ideas, "list_ideas", lambda project_id, s: calls.append((project_id, s)) or [])

    ideas.get_ideas(1, tab)

    assert calls == [(1, statuses)]


@pytest.mark.parametrize(("exc", "status"), [(IdeaNotFound("x"), 404), (IdeaAlreadyDecided("x"), 409)])
def test_reject_maps_errors(monkeypatch, exc, status):
    monkeypatch.setattr(ideas, "reject_idea", _raiser(exc))

    with pytest.raises(HTTPException) as error:
        ideas.post_reject_idea(1, ideas.RejectIdeaRequest(reason="r"))
    assert error.value.status_code == status


def test_routes_are_registered():
    from app.main import app

    paths = app.openapi()["paths"]
    assert "/api/projects/{project_id}/ideas/run" in paths
    assert "/api/ideas/{idea_id}/reject" in paths
    assert "/api/ideas/{idea_id}/approve" in paths


@pytest.fixture
def approval_db(tmp_path, monkeypatch):
    """承認APIが使うDBを一時DBに差し替え、提案を1件保存する"""
    engine = make_engine(str(tmp_path / "test.db"))
    init_db(bind=engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        session.add(Project(id=1, name="p", github_repo="owner/repo", repo_path="C:/repo", default_branch="master"))
        session.add(IdeaJob(id=1, project_id=1, status="succeeded"))
        session.commit()
    monkeypatch.setattr(ideas, "SessionLocal", factory)
    for name in ("claim_idea", "record_issue_created", "record_subtask_created", "release_claim"):
        func = getattr(idea_approval, name)
        monkeypatch.setattr(ideas, name, lambda *args, _f=func: _f(*args, session_factory=factory))
    return factory


def _save_idea(factory, related_issue_number=None) -> int:
    proposal = {
        "category": "feature",
        "title": "提案タイトル",
        "summary": "概要",
        "detail": "",
        "rationale": "根拠",
        "related_files": "a.py:1",
        "related_issue_number": related_issue_number,
    }
    return save_proposals(1, 1, [proposal], session_factory=factory)[0]


@pytest.fixture
def github(monkeypatch):
    """Issue作成・サブタスク作成・実行ジョブ投入の呼び出しを記録する"""
    calls = {"issues": [], "subtasks": [], "executes": []}

    def fake_create_issue(repo, title, body):
        calls["issues"].append((repo, title, body))
        return {"number": 50, "url": "https://example.invalid/issues/50"}

    def fake_create_subtask(payload):
        calls["subtasks"].append(payload)
        return {"id": 9, "title": "t", "github_pr_number": 51}

    def fake_execute(subtask_id):
        calls["executes"].append(subtask_id)
        return {"job_id": 3, "status": "queued"}

    monkeypatch.setattr(ideas, "create_issue", fake_create_issue)
    monkeypatch.setattr(ideas, "create_subtask", fake_create_subtask)
    monkeypatch.setattr(ideas, "execute_subtask", fake_execute)
    return calls


def _approve(idea_id, mode):
    return ideas.post_approve_idea(idea_id, ideas.ApproveIdeaRequest(mode=mode))


def test_approve_issue_only_creates_issue(approval_db, github):
    idea_id = _save_idea(approval_db)

    result = _approve(idea_id, "issue_only")

    assert result["idea"]["status"] == IdeaStatus.ISSUE_CREATED
    assert result["idea"]["created_issue_number"] == 50
    assert result["subtask"] is None
    assert github["issues"][0][:2] == ("owner/repo", "[IdeaMan] 提案タイトル")
    assert github["subtasks"] == []


def test_approve_with_subtask_creates_issue_subtask_and_job(approval_db, github):
    idea_id = _save_idea(approval_db)

    result = _approve(idea_id, "with_subtask")

    assert result["idea"]["status"] == IdeaStatus.SUBTASK_CREATED
    assert result["idea"]["created_subtask_id"] == 9
    payload = github["subtasks"][0]
    assert (payload.github_issue_number, payload.issue_title) == (50, "[IdeaMan] 提案タイトル")
    assert payload.instruction.startswith("アイデアマンの提案を実装する。")
    assert github["executes"] == [9]
    assert result["subtask"]["job"]["job_id"] == 3


def test_approve_existing_issue_idea_skips_issue_creation(approval_db, github):
    idea_id = _save_idea(approval_db, related_issue_number=7)

    result = _approve(idea_id, "with_subtask")

    assert github["issues"] == []
    assert github["subtasks"][0].github_issue_number == 7
    assert github["subtasks"][0].issue_title == ""
    assert result["idea"]["status"] == IdeaStatus.SUBTASK_CREATED


def test_approve_existing_issue_idea_refuses_issue_only(approval_db, github):
    idea_id = _save_idea(approval_db, related_issue_number=7)

    with pytest.raises(HTTPException) as error:
        _approve(idea_id, "issue_only")
    assert error.value.status_code == 409


def test_issue_creation_failure_returns_to_proposed(approval_db, github, monkeypatch):
    monkeypatch.setattr(ideas, "create_issue", _raiser(GitHubClientError("gh error")))
    idea_id = _save_idea(approval_db)

    with pytest.raises(HTTPException) as error:
        _approve(idea_id, "with_subtask")

    assert error.value.status_code == 500
    assert list_ideas(1, session_factory=approval_db)[0]["status"] == IdeaStatus.PROPOSED


def test_subtask_failure_keeps_issue_and_allows_retry(approval_db, github, monkeypatch):
    monkeypatch.setattr(ideas, "create_subtask", _raiser(HTTPException(status_code=500, detail="git error")))
    idea_id = _save_idea(approval_db)

    with pytest.raises(HTTPException) as error:
        _approve(idea_id, "with_subtask")

    assert "git error" in error.value.detail
    assert list_ideas(1, session_factory=approval_db)[0]["status"] == IdeaStatus.ISSUE_CREATED

    monkeypatch.setattr(ideas, "create_subtask", lambda payload: {"id": 9})
    result = _approve(idea_id, "with_subtask")

    assert len(github["issues"]) == 1
    assert result["idea"]["status"] == IdeaStatus.SUBTASK_CREATED


def test_approve_decided_idea_is_refused(approval_db, github):
    idea_id = _save_idea(approval_db)
    _approve(idea_id, "issue_only")

    with pytest.raises(HTTPException) as error:
        _approve(idea_id, "issue_only")
    assert error.value.status_code == 409
