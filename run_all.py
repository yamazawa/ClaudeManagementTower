import os
import subprocess
import sys
import time

from core.config import settings
from core.supervisor_control import (
    COMMAND_RESTART_SERVER,
    COMMAND_RESTART_WORKERS,
    COMMAND_START_WORKERS,
    SUPERVISED_ENV,
    take_requested_commands,
)

SERVER_ARGS = ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"]
WORKERS_ARGS = ["-u", "-m", "worker.launcher"]
STOP_TIMEOUT_SECONDS = 10


class Supervisor:
    """サーバー・ワーカーの起動管理

    サーバーからの要求ファイルを監視し、サーバー再起動・ワーカー起動を行う。
    """

    def __init__(self) -> None:
        self.env = os.environ.copy()
        self.env.setdefault("PYTHONIOENCODING", "utf-8")
        self.env[SUPERVISED_ENV] = "1"
        self.server: subprocess.Popen | None = None
        self.workers: subprocess.Popen | None = None

    def _spawn(self, args: list[str]) -> subprocess.Popen:
        return subprocess.Popen([sys.executable, *args], env=self.env)

    def start_server(self) -> None:
        print("[run_all] サーバーを起動します")
        self.server = self._spawn(SERVER_ARGS)

    def restart_server(self) -> None:
        print("[run_all] サーバーを再起動します")
        _stop(self.server)
        self.start_server()

    def start_workers(self) -> None:
        if self.workers is not None and self.workers.poll() is None:
            print("[run_all] ワーカーは起動済みのため何もしません")
            return
        print("[run_all] ワーカーを起動します")
        self.workers = self._spawn(WORKERS_ARGS)

    def restart_workers(self) -> None:
        print("[run_all] ワーカーを再起動します")
        _stop(self.workers)
        self.workers = self._spawn(WORKERS_ARGS)

    def handle(self, command: str) -> None:
        handlers = {
            COMMAND_RESTART_SERVER: self.restart_server,
            COMMAND_START_WORKERS: self.start_workers,
            COMMAND_RESTART_WORKERS: self.restart_workers,
        }
        handlers[command]()

    def run(self) -> None:
        take_requested_commands()
        self.start_server()
        self.start_workers()
        try:
            while True:
                time.sleep(settings.supervisor_poll_interval_seconds)
                for command in take_requested_commands():
                    self.handle(command)
        except KeyboardInterrupt:
            _stop(self.server)
            _stop(self.workers)


def _stop(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=STOP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def main() -> None:
    Supervisor().run()


if __name__ == "__main__":
    main()
