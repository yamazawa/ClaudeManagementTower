import asyncio

import pytest
from sqlalchemy.orm import sessionmaker

from core import cli_tower_tools as tools
from core.db import init_db, make_engine
from core.git_client import GitClientError
from core.models import Project


@pytest.fixture
def session_factory(tmp_path):
    engine = make_engine(str(tmp_path / "test.db"))
    init_db(bind=engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        session.add(Project(id=1, name="p", github_repo="owner/repo", repo_path="x", default_branch="master"))
        session.commit()
    return factory


MR = {"github_pr_number": 21, "title": "題名ー①", "pr_url": "pr-url"}


@pytest.fixture
def created(monkeypatch):
    """共通の作成処理に渡された値を記録する"""
    calls = []

    def fake_create_issue_with_mr(project, title, body, instruction, session_factory):
        calls.append(("issue_with_mr", project.github_repo, title, body, instruction))
        return {"issue": {"number": 7, "url": "issue-url"}, "mr": MR, "mr_error": None}

    def fake_create_mr(project, issue_number, suffix, instruction, issue_title, session_factory):
        calls.append(("mr", issue_number, suffix, instruction, issue_title))
        return MR

    monkeypatch.setattr(tools, "create_issue_with_mr", fake_create_issue_with_mr)
    monkeypatch.setattr(tools, "create_mr", fake_create_mr)
    monkeypatch.setattr(tools, "get_issue", lambda repo, number: {"title": "題名", "state": "OPEN"})
    return calls


def test_create_issue_with_mr_uses_common_creation(session_factory, created):
    text = tools.run_create_issue_with_mr(1, {"title": "題名", "instruction": "指示"}, session_factory)

    assert created == [("issue_with_mr", "owner/repo", "題名", "", "指示")]
    assert "Issue #7" in text
    assert "#21" in text


def test_create_issue_with_mr_reports_mr_failure(session_factory, monkeypatch):
    failed = {"issue": {"number": 7, "url": "issue-url"}, "mr": None, "mr_error": "push失敗"}
    monkeypatch.setattr(tools, "create_issue_with_mr", lambda *args, **kwargs: failed)

    text = tools.run_create_issue_with_mr(1, {"title": "題名"}, session_factory)

    assert "Issue #7" in text
    assert "push失敗" in text


def test_create_mr_passes_fetched_issue_title(session_factory, created):
    tools.run_create_mr(1, {"issue_number": 7, "title": "追加"}, session_factory)

    assert created == [("mr", 7, "追加", "", "題名")]


def test_create_mr_refuses_closed_issue(session_factory, created, monkeypatch):
    monkeypatch.setattr(tools, "get_issue", lambda repo, number: {"title": "題名", "state": "CLOSED"})

    with pytest.raises(tools.ToolFailure):
        tools.run_create_mr(1, {"issue_number": 7}, session_factory)

    assert created == []


def test_unknown_project_is_failure(session_factory):
    with pytest.raises(tools.ToolFailure):
        tools.run_create_issue(99, {"title": "題名"}, session_factory)


def _failing_runner(exc):
    def runner(project_id, args):
        raise exc

    return runner


def test_call_returns_expected_failure_as_tool_error():
    result = asyncio.run(tools._call(_failing_runner(GitClientError("push失敗")), 1, {}))

    assert result["is_error"] is True
    assert result["content"][0]["text"] == "push失敗"


def test_call_returns_text():
    result = asyncio.run(tools._call(lambda project_id, args: f"#{project_id}", 1, {}))

    assert result == {"content": [{"type": "text", "text": "#1"}]}


def test_build_tower_server_names_server():
    server = tools.build_tower_server(1)

    assert server["name"] == tools.TOWER_SERVER_NAME
