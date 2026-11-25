from datetime import datetime

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy.orm import sessionmaker

from app.routes import projects
from core import issue_mr_creation
from core.db import init_db, make_engine
from core.models import Project, Subtask
from core.repo_setup import NewRepo, RepoSetupError


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

    assert (project["display_name"], project["repo_url"]) == (
        "p",
        "https://github.com/owner/repo",
    )


def test_get_projects_uses_registered_display_name_and_description(session_factory):
    with session_factory() as session:
        project = session.get(Project, 1)
        project.display_name = "日本語名"
        project.description = "説明"
        session.commit()

    [project] = projects.get_projects()

    assert (project["display_name"], project["description"]) == ("日本語名", "説明")


def test_remove_project_hides_project_from_list(session_factory):
    result = projects.remove_project(1)

    assert result == {"id": 1, "removed": True}
    assert projects.get_projects() == []
    with session_factory() as session:
        assert session.get(Project, 1).removed is True


def test_remove_project_returns_404_for_unknown_project(session_factory):
    with pytest.raises(HTTPException) as exc_info:
        projects.remove_project(99)

    assert exc_info.value.status_code == 404


def test_create_project_passes_normalized_repo(monkeypatch):
    calls = []
    monkeypatch.setattr(projects, "create_repository", lambda repo: calls.append(repo) or {"project_id": 3})

    result = projects.create_project(projects.CreateProjectRequest(name=" a ", display_name="名", description="説明"))

    assert result == {"project_id": 3}
    assert calls == [NewRepo("a", "名", "説明")]


def test_create_project_rejects_invalid_name_with_400():
    with pytest.raises(HTTPException) as exc_info:
        projects.create_project(projects.CreateProjectRequest(name="日本語", display_name="名", description="説明"))

    assert exc_info.value.status_code == 400


def test_create_project_returns_registered_id_on_setup_failure(monkeypatch):
    def fail(repo):
        raise RepoSetupError("初期設定に失敗", project_id=5)

    monkeypatch.setattr(projects, "create_repository", fail)

    with pytest.raises(HTTPException) as exc_info:
        projects.create_project(projects.CreateProjectRequest(name="a", display_name="名", description="説明"))

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == {"message": "初期設定に失敗", "project_id": 5}


def test_get_issues_passes_state(session_factory, monkeypatch):
    calls = _capture_list_issues(monkeypatch)

    projects.get_issues(1, "closed")

    assert calls == [("owner/repo", "closed")]


def test_get_issues_defaults_to_open(session_factory, monkeypatch):
    calls = _capture_list_issues(monkeypatch)

    projects.get_issues(1)

    assert calls == [("owner/repo", "open")]


def test_get_issues_closed_today_lists_issues_closed_since_midnight(
    session_factory, monkeypatch
):
    calls = []

    def fake(repo, since):
        calls.append((repo, since))
        return [{"number": 8, "state": "CLOSED"}]

    monkeypatch.setattr(projects, "list_issues_closed_since", fake)
    monkeypatch.setattr(projects, "list_issues", lambda repo, state: pytest.fail("not used"))

    issues = projects.get_issues(1, "closed_today")

    [(repo, since)] = calls
    assert repo == "owner/repo"
    assert since.tzinfo is not None
    assert (since.hour, since.minute, since.second, since.microsecond) == (0, 0, 0, 0)
    assert since.date() == datetime.now().astimezone().date()
    assert [i["number"] for i in issues] == [8]


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

    assert projects.get_mr_counts(1) == {
        5: {"resolved": 1, "unresolved": 1, "total": 2}
    }


def test_mr_counts_treat_deployed_as_resolved(session_factory):
    _add_subtasks(session_factory, 5, ["merged", "deployed", "draft"])

    assert projects.get_mr_counts(1)[5] == {"resolved": 2, "unresolved": 1, "total": 3}


def test_get_issues_passes_state_filter_to_github(session_factory, monkeypatch):
    calls = []

    def fake(repo, state):
        calls.append(state)
        return [{"number": 6, "state": "CLOSED"}]

    monkeypatch.setattr(projects, "list_issues", fake)
    _add_subtasks(session_factory, 6, ["resolved"])

    issues = projects.get_issues(1, "closed")

    assert calls == ["closed"]
    assert [i["number"] for i in issues] == [6]


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

    monkeypatch.setattr(issue_mr_creation, "create_github_issue", fake)

    result = projects.create_project_issue(1, projects.CreateIssueRequest(title="  題名  "))

    assert calls == ["題名"]
    assert (result["number"], result["title"]) == (7, "題名")


def test_create_issue_with_blank_title_is_bad_request(session_factory):
    with pytest.raises(HTTPException) as error:
        projects.create_project_issue(1, projects.CreateIssueRequest(title="  "))
    assert error.value.status_code == 400


def test_create_issue_with_mr_links_pr_after_response(session_factory, monkeypatch):
    calls = []

    def fake(project, title, body, run_later, session_factory):
        run_later(calls.append, "linked")
        return {"issue": {"number": 7}, "mr": {"id": 1}, "mr_error": None}

    monkeypatch.setattr(projects, "create_issue_with_mr", fake)
    background = BackgroundTasks()

    result = projects.create_project_issue_with_mr(1, projects.CreateIssueRequest(title="題名"), background)

    assert result["mr"]["id"] == 1
    assert calls == []
    for task in background.tasks:
        task.func(*task.args, **task.kwargs)
    assert calls == ["linked"]


def test_create_issue_with_mr_blank_title_is_bad_request(session_factory):
    with pytest.raises(HTTPException) as error:
        projects.create_project_issue_with_mr(1, projects.CreateIssueRequest(title=" "), BackgroundTasks())
    assert error.value.status_code == 400
