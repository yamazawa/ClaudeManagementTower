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


def _add_subtasks(session_factory, issue_number, states):
    with session_factory() as session:
        session.add_all(
            Subtask(
                project_id=1,
                github_issue_number=issue_number,
                title="t",
                instruction="",
                branch_name=f"b-{issue_number}-{i}",
                lifecycle_state=state,
            )
            for i, state in enumerate(states)
        )
        session.commit()


def test_get_issues_includes_mr_counts(session_factory, monkeypatch):
    monkeypatch.setattr(
        projects, "list_issues", lambda repo, state: [{"number": 5}, {"number": 6}]
    )
    _add_subtasks(session_factory, 5, ["merged", "merged", "resolved", "canceled", "draft"])

    issues = projects.get_issues(1)

    assert [i["mr_counts"] for i in issues] == [
        {"resolved": 2, "unresolved": 2, "total": 4},
        {"resolved": 0, "unresolved": 0, "total": 0},
    ]


def test_get_mr_counts_returns_db_counts(session_factory, monkeypatch):
    def fail(repo, state):
        raise AssertionError("should not call GitHub")

    monkeypatch.setattr(projects, "list_issues", fail)
    _add_subtasks(session_factory, 5, ["merged", "resolved", "canceled"])
    _add_subtasks(session_factory, 7, ["canceled"])

    assert projects.get_mr_counts(1) == {5: {"resolved": 1, "unresolved": 1, "total": 2}}


def test_mr_counts_treat_deployed_as_resolved(session_factory):
    _add_subtasks(session_factory, 5, ["merged", "deployed", "draft"])

    assert projects.get_mr_counts(1)[5] == {"resolved": 2, "unresolved": 1, "total": 3}


def test_get_mr_counts_unknown_project(session_factory):
    with pytest.raises(HTTPException) as error:
        projects.get_mr_counts(99)
    assert error.value.status_code == 404


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
                lifecycle_state="resolved",
            )
        )
        session.commit()

    subtasks = projects.get_issue_subtasks(1, 5)

    assert [(s["lifecycle_state"], s["pr_url"]) for s in subtasks] == [
        ("resolved", "https://github.com/owner/repo/pull/9")
    ]


def test_get_issue_subtasks_unknown_project(session_factory):
    with pytest.raises(HTTPException) as error:
        projects.get_issue_subtasks(99, 5)
    assert error.value.status_code == 404


def test_create_issue_strips_title_and_returns_it(session_factory, monkeypatch):
    calls = []

    def fake(repo, title, body):
        calls.append(title)
        return {"number": 7, "url": "https://github.com/owner/repo/issues/7"}

    monkeypatch.setattr(projects, "create_issue", fake)

    result = projects.create_project_issue(1, projects.CreateIssueRequest(title="  題名  "))

    assert calls == ["題名"]
    assert (result["number"], result["title"]) == (7, "題名")


def test_create_issue_with_blank_title_is_bad_request(session_factory):
    with pytest.raises(HTTPException) as error:
        projects.create_project_issue(1, projects.CreateIssueRequest(title="  "))
    assert error.value.status_code == 400
