import json
import sys

import pytest

from core import deploy
from core.deploy import (
    DeployAlreadyRunning,
    DeployError,
    DeployNotDefined,
    is_deploy_defined,
    load_steps,
    read_result,
    run_deploy,
    start_deploy,
)
from core.git_client import GitClientError
from core.supervisor_control import COMMAND_RESTART_SERVER, COMMAND_RESTART_WORKERS


@pytest.fixture
def control(monkeypatch, tmp_path):
    monkeypatch.setattr(deploy.settings, "supervisor_control_dir", str(tmp_path / "control"))
    commands = []
    monkeypatch.setattr(deploy, "request_command", commands.append)
    monkeypatch.setattr(deploy, "mark_deployed", lambda project_id, repo_path: [])
    return commands


def _write_definition(repo, content) -> None:
    path = repo / ".claude-tower" / "deploy.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    text = content if isinstance(content, str) else json.dumps(content)
    path.write_text(text, encoding="utf-8")


def test_not_defined_when_file_missing(tmp_path):
    assert not is_deploy_defined(str(tmp_path))
    with pytest.raises(DeployNotDefined):
        load_steps(str(tmp_path))


def test_load_steps_returns_defined_steps(tmp_path):
    steps = [{"type": "pull"}, {"type": "restart_server"}]
    _write_definition(tmp_path, {"steps": steps})

    assert is_deploy_defined(str(tmp_path))
    assert load_steps(str(tmp_path)) == steps


@pytest.mark.parametrize(
    "content",
    [
        "{broken",
        {"steps": []},
        {"steps": [{"type": "unknown"}]},
        {"steps": [{"type": "command"}]},
        [],
    ],
)
def test_load_steps_rejects_invalid_definition(tmp_path, content):
    _write_definition(tmp_path, content)

    with pytest.raises(DeployError):
        load_steps(str(tmp_path))


def test_pulls_then_requests_restart(monkeypatch, control):
    pulled = []
    monkeypatch.setattr(deploy, "pull_latest", lambda path, branch: pulled.append((path, branch)))

    run_deploy(1, "repo", "master", [{"type": "pull"}, {"type": "restart_server"}])

    assert pulled == [("repo", "master")]
    assert read_result(1) == {"status": "done", "restarts": [COMMAND_RESTART_SERVER]}
    assert control == [COMMAND_RESTART_SERVER]


def test_pull_uses_branch_in_step(monkeypatch, control):
    pulled = []
    monkeypatch.setattr(deploy, "pull_latest", lambda path, branch: pulled.append(branch))

    run_deploy(1, "repo", "master", [{"type": "pull", "branch": "release"}])

    assert pulled == ["release"]


def test_restarts_requested_after_all_steps(monkeypatch, control):
    order = []
    monkeypatch.setattr(deploy, "pull_latest", lambda path, branch: order.append("pull"))
    monkeypatch.setattr(deploy, "request_command", order.append)

    run_deploy(
        1, "repo", "master", [{"type": "restart_workers"}, {"type": "pull"}, {"type": "restart_server"}]
    )

    assert order == ["pull", COMMAND_RESTART_WORKERS, COMMAND_RESTART_SERVER]


def test_failed_step_stops_and_skips_restart(monkeypatch, control):
    def fail(path, branch):
        raise GitClientError("pull失敗")

    monkeypatch.setattr(deploy, "pull_latest", fail)

    run_deploy(1, "repo", "master", [{"type": "pull"}, {"type": "restart_server"}])

    assert read_result(1) == {"status": "failed", "error": "pull失敗"}
    assert control == []


def test_marks_deployed_before_restart(monkeypatch, control):
    order = []
    monkeypatch.setattr(deploy, "pull_latest", lambda path, branch: order.append("pull"))
    monkeypatch.setattr(
        deploy, "mark_deployed", lambda project_id, repo_path: order.append(("mark", project_id, repo_path))
    )
    monkeypatch.setattr(deploy, "request_command", order.append)

    run_deploy(1, "repo", "master", [{"type": "pull"}, {"type": "restart_server"}])

    assert order == ["pull", ("mark", 1, "repo"), COMMAND_RESTART_SERVER]


def test_mark_deployed_failure_keeps_deploy_done(monkeypatch, control):
    def fail(project_id, repo_path):
        raise RuntimeError("gh失敗")

    monkeypatch.setattr(deploy, "pull_latest", lambda path, branch: None)
    monkeypatch.setattr(deploy, "mark_deployed", fail)

    run_deploy(1, "repo", "master", [{"type": "pull"}, {"type": "restart_server"}])

    assert read_result(1) == {"status": "done", "restarts": [COMMAND_RESTART_SERVER]}
    assert control == [COMMAND_RESTART_SERVER]


def test_failed_step_skips_mark_deployed(monkeypatch, control):
    marked = []

    def fail(path, branch):
        raise GitClientError("pull失敗")

    monkeypatch.setattr(deploy, "pull_latest", fail)
    monkeypatch.setattr(deploy, "mark_deployed", lambda project_id, repo_path: marked.append(project_id))

    run_deploy(1, "repo", "master", [{"type": "pull"}])

    assert marked == []


def test_command_runs_in_repo(tmp_path, control):
    script = "import pathlib; pathlib.Path('out.txt').write_text('ok')"
    run_deploy(1, str(tmp_path), "master", [{"type": "command", "run": f'"{sys.executable}" -c "{script}"'}])

    assert read_result(1)["status"] == "done"
    assert (tmp_path / "out.txt").read_text() == "ok"


def test_command_failure_recorded(tmp_path, control):
    command = f'"{sys.executable}" -c "import sys; sys.exit(3)"'

    run_deploy(1, str(tmp_path), "master", [{"type": "command", "run": command}])

    result = read_result(1)
    assert result["status"] == "failed"
    assert "終了コード3" in result["error"]


def test_start_deploy_rejects_while_running(control):
    pending = []

    start_deploy(1, "repo", "master", [], start_thread=pending.append)
    assert read_result(1) == {"status": "running"}
    with pytest.raises(DeployAlreadyRunning):
        start_deploy(1, "repo", "master", [], start_thread=pending.append)

    pending[0]()
    start_deploy(1, "repo", "master", [], start_thread=lambda run: None)
    deploy._running_project_ids.discard(1)


def test_start_deploy_allows_other_project_in_parallel(control):
    start_deploy(1, "repo", "master", [], start_thread=lambda run: None)
    start_deploy(2, "repo", "master", [], start_thread=lambda run: None)
    deploy._running_project_ids.clear()
