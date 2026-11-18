import os
import subprocess
import sys
import time

from core.config import settings
from core.db import init_db
from core.supervisor_control import (
    COMMAND_RESTART_SERVER,
    COMMAND_RESTART_WORKERS,
    COMMAND_START_WORKERS,
    SUPERVISED_ENV,
    take_requested_commands,
)
from worker.pool import WorkerPool, spawn_worker, stop_process

SERVER_ARGS = ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"]


class Supervisor:
    """サーバー・ワーカーの起動管理

    サーバーからの要求ファイルを監視し、サーバー再起動・ワーカー起動を行う。
    ワーカーは中間プロセスを挟まず、ワーカープールで直接管理する。
    """

    def __init__(self, pool: WorkerPool | None = None) -> None:
        self.env = os.environ.copy()
        self.env.setdefault("PYTHONIOENCODING", "utf-8")
        self.env[SUPERVISED_ENV] = "1"
        self.server: subprocess.Popen | None = None
        self.workers = pool or WorkerPool(settings.worker_count, spawn=lambda: spawn_worker(self.env))

    def _spawn(self, args: list[str]) -> subprocess.Popen:
        return subprocess.Popen([sys.executable, *args], env=self.env)

    def start_server(self) -> None:
        print("[run_all] サーバーを起動します")
        self.server = self._spawn(SERVER_ARGS)

    def restart_server(self) -> None:
        print("[run_all] サーバーを再起動します")
        stop_process(self.server)
        self.start_server()

    def start_workers(self) -> None:
        if self.workers.is_running():
            print("[run_all] ワーカーは起動済みのため何もしません")
            return
        self.workers.start()

    def restart_workers(self) -> None:
        print("[run_all] ワーカーを再起動します")
        self.workers.start()

    def handle(self, command: str) -> None:
        handlers = {
            COMMAND_RESTART_SERVER: self.restart_server,
            COMMAND_START_WORKERS: self.start_workers,
            COMMAND_RESTART_WORKERS: self.restart_workers,
        }
        handlers[command]()

    def tick(self) -> None:
        for command in take_requested_commands():
            self.handle(command)
        self.workers.maintain()

    def run(self) -> None:
        take_requested_commands()
        self.start_server()
        self.start_workers()
        try:
            while True:
                time.sleep(settings.supervisor_poll_interval_seconds)
                self.tick()
        except KeyboardInterrupt:
            stop_process(self.server)
            self.workers.stop()


def main() -> None:
    init_db()
    Supervisor().run()


if __name__ == "__main__":
    main()
