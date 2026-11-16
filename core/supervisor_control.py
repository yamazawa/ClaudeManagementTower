"""スーパーバイザー(run_all.py)への操作要求

サーバーからの要求を制御ディレクトリ内の要求ファイルで受け渡す。
スーパーバイザーは要求ファイルを定期的に取り出して処理する。
"""

import os
from pathlib import Path

from core.config import settings

SUPERVISED_ENV = "CLAUDE_TOWER_SUPERVISED"

COMMAND_RESTART_SERVER = "restart_server"
COMMAND_START_WORKERS = "start_workers"
ALL_COMMANDS = (COMMAND_RESTART_SERVER, COMMAND_START_WORKERS)

_REQUEST_SUFFIX = ".request"


def is_supervised() -> bool:
    return os.environ.get(SUPERVISED_ENV) == "1"


def _request_path(command: str, control_dir: str | None) -> Path:
    return Path(control_dir or settings.supervisor_control_dir) / f"{command}{_REQUEST_SUFFIX}"


def request_command(command: str, control_dir: str | None = None) -> None:
    if command not in ALL_COMMANDS:
        raise ValueError(f"未知のコマンド: {command}")
    path = _request_path(command, control_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()


def _take(command: str, control_dir: str | None) -> bool:
    path = _request_path(command, control_dir)
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    return True


def take_requested_commands(control_dir: str | None = None) -> list[str]:
    return [command for command in ALL_COMMANDS if _take(command, control_dir)]
