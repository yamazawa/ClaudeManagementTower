import pytest
from sqlalchemy.orm import sessionmaker

from core import issue_mr_creation as creation
from core.db import init_db, make_engine
from core.github_client import GitHubClientError
from core.git_client import GitClientError
from core.models import Project, Subtask


@pytest.fixture
def session_factory(tmp_path):
    engine = make_engine(str(tmp_path / "test.db"))
    init_db(bind=engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        session.add(_project())
        session.commit()
    return factory


def _project():
    return Project(id=1, name="p", github_repo="owner/repo", repo_path="x", default_branch="master")


@pytest.fixture
def github(monkeypatch):
    """Issue作成・MR作成・PR操作の呼び出しを記録する"""
    calls = {"issues": [], "pushed": [], "closed": [], "edited": []}

    def fake_create_issue(repo, title, body):
        calls["issues"].append((repo, title, body))
        return {"number": 7, "url": "issue-url"}

    def fake_push(project, branch_name, title, instruction, body):
        calls["pushed"].append({"branch_name": branch_name, "title": title, "instruction": instruction, "body": body})
        return {"number": 21, "url": "pr-url"}

    monkeypatch.setattr(creation, "create_github_issue", fake_create_issue)
    monkeypatch.setattr(creation, "_push_draft_pr", fake_push)
    monkeypatch.setattr(creation, "close_pr", lambda *args: calls["closed"].append(args))
    monkeypatch.setattr(creation, "edit_pr_body", lambda *args: calls["edited"].append(args))
    return calls


def _raiser(exc):
    def raise_error(*args, **kwargs):
        raise exc

    return raise_error


def _run_now(func, *args):
    func(*args)


def test_create_issue_strips_title(github):
    issue = creation.create_issue(_project(), "  題名  ", "本文")

    assert issue == {"number": 7, "url": "issue-url", "title": "題名"}
    assert github["issues"] == [("owner/repo", "題名", "本文")]


def test_create_issue_rejects_blank_title(github):
    with pytest.raises(creation.EmptyTitleError):
        creation.create_issue(_project(), "  ")

    assert github["issues"] == []


def test_create_issue_with_mr_creates_linked_mr(session_factory, github):
    result = creation.create_issue_with_mr(
        _project(), " あいうえお ", "本文", "指示", run_later=_run_now, session_factory=session_factory
    )

    assert result["issue"]["number"] == 7
    assert result["mr_error"] is None
    assert result["mr"]["title"] == "あいうえおー①"
    assert github["pushed"][0]["instruction"] == "指示"
    assert github["pushed"][0]["branch_name"].startswith("issue-new-")
    assert github["edited"] == [("owner/repo", 21, "Related to #7")]
    with session_factory() as session:
        row = session.get(Subtask, result["mr"]["id"])
        assert (row.github_issue_number, row.github_pr_number, row.instruction) == (7, 21, "指示")


def test_create_issue_with_mr_reports_mr_failure(session_factory, github, monkeypatch):
    monkeypatch.setattr(creation, "_push_draft_pr", _raiser(GitClientError("push失敗")))

    result = creation.create_issue_with_mr(_project(), "あ", run_later=_run_now, session_factory=session_factory)

    assert (result["issue"]["number"], result["mr"], result["mr_error"]) == (7, None, "push失敗")
    with session_factory() as session:
        assert session.query(Subtask).count() == 0


def test_create_issue_with_mr_closes_mr_on_issue_failure(session_factory, github, monkeypatch):
    monkeypatch.setattr(creation, "create_github_issue", _raiser(GitHubClientError("gh失敗")))

    with pytest.raises(GitHubClientError):
        creation.create_issue_with_mr(_project(), "あ", run_later=_run_now, session_factory=session_factory)

    assert github["closed"] == [("owner/repo", 21)]
    with session_factory() as session:
        assert session.query(Subtask).count() == 0


def test_create_issue_with_mr_skips_close_when_both_fail(session_factory, github, monkeypatch):
    monkeypatch.setattr(creation, "create_github_issue", _raiser(GitHubClientError("gh失敗")))
    monkeypatch.setattr(creation, "_push_draft_pr", _raiser(GitClientError("push失敗")))

    with pytest.raises(GitHubClientError):
        creation.create_issue_with_mr(_project(), "あ", run_later=_run_now, session_factory=session_factory)

    assert github["closed"] == []


def test_create_mr_uses_given_issue_title_and_instruction(session_factory, github, monkeypatch):
    monkeypatch.setattr(creation, "get_issue", _raiser(AssertionError("get_issue should not be called")))

    mr = creation.create_mr(
        _project(), 5, instruction="指示", issue_title="さしすせそ", session_factory=session_factory
    )

    assert mr["title"] == "さしすせそー①"
    assert github["pushed"][0]["body"] == "Related to #5"
    with session_factory() as session:
        assert session.get(Subtask, mr["id"]).instruction == "指示"
