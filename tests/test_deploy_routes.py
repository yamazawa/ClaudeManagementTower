import json

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker

from app.routes import deploy, projects
from core.db import init_db, make_engine
from core.deploy import DeployAlreadyRunning
from core.git_client import GitClientError
from core.models import Project
from core.supervisor_control import COMMAND_RESTART_SERVER


@pytest.fixture
def repo(tmp_path, monkeypatch):
    engine = make_engine(str(tmp_path / "test.db"))
    init_db(bind=engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(deploy, "SessionLocal", factory)
    monkeypatch.setattr(projects, "SessionLocal", factory)
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    with factory() as session:
        session.add(
            Project(name="p", github_repo="owner/repo", repo_path=str(repo_path), default_branch="main")
        )
        session.commit()
    return repo_path


def _define(repo_path, steps) -> None:
    path = repo_path / ".claude-tower" / "deploy.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"steps": steps}), encoding="utf-8")


def _status_code(call) -> int:
    with pytest.raises(HTTPException) as error:
        call()
    return error.value.status_code


def test_projects_report_whether_deploy_defined(repo):
    assert projects.get_projects()[0]["deploy_defined"] is False
    _define(repo, [{"type": "pull"}])
    assert projects.get_projects()[0]["deploy_defined"] is True


def test_deploy_without_definition_only_marks_deployed(repo, monkeypatch):
    finished = []
    monkeypatch.setattr(deploy, "finish_without_steps", finished.append)
    monkeypatch.setattr(deploy, "start_deploy", lambda *args: pytest.fail("not called"))

    assert deploy.deploy_project(1) == {"accepted": True, "restarts": [], "skipped": True}
    assert finished == [1]


def test_deploy_rejected_when_definition_invalid(repo):
    _define(repo, [{"type": "unknown"}])
    assert _status_code(lambda: deploy.deploy_project(1)) == 400


def test_deploy_404_for_unknown_project(repo):
    assert _status_code(lambda: deploy.deploy_project(99)) == 404


def test_restart_rejected_when_not_supervised(repo, monkeypatch):
    _define(repo, [{"type": "pull"}, {"type": "restart_server"}])
    monkeypatch.setattr(deploy, "is_supervised", lambda: False)

    assert _status_code(lambda: deploy.deploy_project(1)) == 409


def test_deploy_without_restart_allowed_when_not_supervised(repo, monkeypatch):
    _define(repo, [{"type": "pull"}])
    monkeypatch.setattr(deploy, "is_supervised", lambda: False)
    started = []
    monkeypatch.setattr(deploy, "start_deploy", lambda *args: started.append(args))

    assert deploy.deploy_project(1) == {"accepted": True, "restarts": []}
    assert started == [(1, str(repo), "main", [{"type": "pull"}])]


def test_deploy_starts_with_restart_when_supervised(repo, monkeypatch):
    _define(repo, [{"type": "pull"}, {"type": "restart_server"}])
    monkeypatch.setattr(deploy, "is_supervised", lambda: True)
    monkeypatch.setattr(deploy, "start_deploy", lambda *args: None)

    assert deploy.deploy_project(1) == {"accepted": True, "restarts": [COMMAND_RESTART_SERVER]}


def test_deploy_rejected_while_running(repo, monkeypatch):
    _define(repo, [{"type": "pull"}])

    def already_running(*args):
        raise DeployAlreadyRunning("実行中")

    monkeypatch.setattr(deploy, "start_deploy", already_running)

    assert _status_code(lambda: deploy.deploy_project(1)) == 409


def test_pending_false_when_not_defined_or_no_pull(repo, monkeypatch):
    monkeypatch.setattr(deploy, "has_remote_updates", lambda *args: pytest.fail("not called"))
    assert deploy.get_deploy_pending(1) == {"pending": False}

    _define(repo, [{"type": "command", "run": "echo"}])
    assert deploy.get_deploy_pending(1) == {"pending": False}


def test_pending_checks_pull_branch(repo, monkeypatch):
    _define(repo, [{"type": "pull", "branch": "release"}])
    calls = []
    monkeypatch.setattr(deploy, "has_remote_updates", lambda *args: calls.append(args) or True)

    assert deploy.get_deploy_pending(1) == {"pending": True}
    assert calls == [(str(repo), "release")]


def test_pending_500_when_git_fails(repo, monkeypatch):
    _define(repo, [{"type": "pull"}])

    def fail(*args):
        raise GitClientError("fetch failed")

    monkeypatch.setattr(deploy, "has_remote_updates", fail)
    assert _status_code(lambda: deploy.get_deploy_pending(1)) == 500


def test_get_deploy_result(monkeypatch):
    monkeypatch.setattr(deploy, "read_result", lambda project_id: {"status": "running"})
    assert deploy.get_deploy_result(1) == {"status": "running"}

    monkeypatch.setattr(deploy, "read_result", lambda project_id: None)
    assert _status_code(lambda: deploy.get_deploy_result(1)) == 404
