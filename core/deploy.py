"""デプロイ（リポジトリごとに定義した手順を実行する）

手順は対象リポジトリの.claude-tower/deploy.jsonに定義する。
定義が無いリポジトリはデプロイできない。
再起動の手順は、他の手順が全て成功した後にまとめて要求する。
サーバー再起動後も結果を参照できるよう、制御ディレクトリにファイルで残す。
"""

import json
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path

from core.config import settings
from core.deploy_tracking import mark_deployed
from core.git_client import GitClientError, pull_latest
from core.supervisor_control import COMMAND_RESTART_SERVER, COMMAND_RESTART_WORKERS, request_command

DEPLOY_FILE = Path(".claude-tower") / "deploy.json"

STEP_PULL = "pull"
STEP_COMMAND = "command"
STEP_RESTART_SERVER = "restart_server"
STEP_RESTART_WORKERS = "restart_workers"
RESTART_STEPS = {
    STEP_RESTART_SERVER: COMMAND_RESTART_SERVER,
    STEP_RESTART_WORKERS: COMMAND_RESTART_WORKERS,
}
ALL_STEPS = (STEP_PULL, STEP_COMMAND, *RESTART_STEPS)

DEFAULT_COMMAND_TIMEOUT_SECONDS = 600
ERROR_OUTPUT_TAIL_CHARS = 1000

STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"

_guard = threading.Lock()
_running_project_ids: set[int] = set()


class DeployError(RuntimeError):
    pass


class DeployNotDefined(DeployError):
    pass


class DeployAlreadyRunning(RuntimeError):
    pass


def deploy_file_path(repo_path: str) -> Path:
    return Path(repo_path) / DEPLOY_FILE


def is_deploy_defined(repo_path: str) -> bool:
    return deploy_file_path(repo_path).is_file()


def load_steps(repo_path: str) -> list[dict]:
    """デプロイ定義の読み込み

    定義が無い場合はDeployNotDefined、形式が不正な場合はDeployErrorを送出する。
    """
    path = deploy_file_path(repo_path)
    if not path.is_file():
        raise DeployNotDefined(f"{DEPLOY_FILE.as_posix()}が定義されていません")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeployError(f"{DEPLOY_FILE.as_posix()}を読み込めません: {exc}") from exc
    steps = data.get("steps") if isinstance(data, dict) else None
    if not isinstance(steps, list) or not steps:
        raise DeployError(f"{DEPLOY_FILE.as_posix()}にstepsが定義されていません")
    for step in steps:
        _validate_step(step)
    return steps


def _validate_step(step) -> None:
    if not isinstance(step, dict) or step.get("type") not in ALL_STEPS:
        raise DeployError(f"不正なデプロイ手順です: {step}")
    if step["type"] == STEP_COMMAND and not isinstance(step.get("run"), str):
        raise DeployError(f"commandの手順にrunが定義されていません: {step}")


def pull_branch(steps: list[dict], default_branch: str) -> str | None:
    """デプロイで取り込むブランチ（pull手順が無ければNone）"""
    pulls = [s for s in steps if s["type"] == STEP_PULL]
    return (pulls[0].get("branch") or default_branch) if pulls else None


def restart_commands(steps: list[dict]) -> list[str]:
    return [RESTART_STEPS[s["type"]] for s in steps if s["type"] in RESTART_STEPS]


def result_path(project_id: int) -> Path:
    return Path(settings.supervisor_control_dir) / f"deploy-result-{project_id}.json"


def read_result(project_id: int) -> dict | None:
    path = result_path(project_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_result(project_id: int, result: dict) -> None:
    path = result_path(project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")


def is_deploy_running(project_id: int) -> bool:
    """デプロイ実行中か

    サーバー再起動で中断した結果ファイルを実行中と誤らないよう、プロセス内の状態で判定する。
    """
    with _guard:
        return project_id in _running_project_ids


def start_deploy(
    project_id: int,
    repo_path: str,
    branch: str,
    steps: list[dict],
    start_thread: Callable[[Callable[[], None]], None] | None = None,
) -> None:
    """デプロイを別スレッドで開始する（同じリポジトリで実行中なら例外）"""
    with _guard:
        if project_id in _running_project_ids:
            raise DeployAlreadyRunning("デプロイは実行中です")
        _running_project_ids.add(project_id)
    _write_result(project_id, {"status": STATUS_RUNNING})

    def run() -> None:
        try:
            run_deploy(project_id, repo_path, branch, steps)
        except Exception as exc:
            # 想定外の例外でも結果を残し、画面が実行中のまま待ち続けないようにする
            _write_result(project_id, {"status": STATUS_FAILED, "error": str(exc)})
        finally:
            with _guard:
                _running_project_ids.discard(project_id)

    (start_thread or _start_daemon_thread)(run)


def _start_daemon_thread(target: Callable[[], None]) -> None:
    threading.Thread(target=target, daemon=True).start()


def run_deploy(project_id: int, repo_path: str, branch: str, steps: list[dict]) -> None:
    try:
        for step in steps:
            _run_step(repo_path, branch, step)
    except (GitClientError, DeployError) as exc:
        _write_result(project_id, {"status": STATUS_FAILED, "error": str(exc)})
        return

    # サーバー再起動の要求前に、デプロイしたソースに含まれるMRを反映する
    mark_deployed_safely(lambda: mark_deployed(project_id, repo_path))
    restarts = restart_commands(steps)
    _write_result(project_id, {"status": STATUS_DONE, "restarts": restarts})
    for command in restarts:
        request_command(command)


def mark_deployed_safely(mark: Callable[[], list[int]]) -> None:
    """MRのDeployed反映

    反映に失敗してもデプロイ自体は成功しているため、失敗扱いにしない。
    """
    try:
        mark()
    except Exception as exc:  # noqa: BLE001
        print(f"[deploy] MRのDeployed反映に失敗しました: {exc}")


def _run_step(repo_path: str, branch: str, step: dict) -> None:
    if step["type"] == STEP_PULL:
        pull_latest(repo_path, step.get("branch") or branch)
    if step["type"] == STEP_COMMAND:
        _run_command(repo_path, step)


def _run_command(repo_path: str, step: dict) -> None:
    command = step["run"]
    timeout = step.get("timeout_seconds", DEFAULT_COMMAND_TIMEOUT_SECONDS)
    try:
        completed = subprocess.run(
            command,
            shell=True,
            cwd=repo_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise DeployError(f"コマンドがタイムアウトしました: {command}") from exc
    if completed.returncode != 0:
        output = (completed.stderr or completed.stdout).strip()[-ERROR_OUTPUT_TAIL_CHARS:]
        raise DeployError(f"コマンドが失敗しました（終了コード{completed.returncode}）: {command}\n{output}")
