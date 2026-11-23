import logging
import os
import subprocess
import sys
import time
from pathlib import Path

from filelock import FileLock, Timeout

from core.config import settings
from core.db import init_db
from core.logging_config import configure_logging
from core.supervisor_control import (
    COMMAND_RESTART_SERVER,
    COMMAND_RESTART_WORKERS,
    COMMAND_START_WORKERS,
    SUPERVISED_ENV,
    take_requested_commands,
)
from worker.pool import WorkerPool, spawn_worker, stop_process

# python run_all.py で起動すると__name__が__main__になるため、名前を固定する
logger = logging.getLogger("run_all")

SERVER_ARGS = ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"]
SINGLETON_LOCK_PATH = Path(settings.supervisor_control_dir) / "supervisor.lock"


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
        logger.info("サーバーを起動します")
        self.server = self._spawn(SERVER_ARGS)

    def restart_server(self) -> None:
        logger.info("サーバーを再起動します")
        stop_process(self.server)
        self.start_server()

    def start_workers(self) -> None:
        if self.workers.is_running():
            logger.info("ワーカーは起動済みのため何もしません")
            return
        self.workers.start()

    def restart_workers(self) -> None:
        logger.info("ワーカーを再起動します")
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


def try_acquire_singleton_lock(path: Path) -> FileLock | None:
    """既に起動中であれば取得できないロックを試みる

    run_all.pyの多重起動（サーバー・ワーカーの奪い合い）を防ぐため、
    取得できない場合はNoneを返す。呼び出し側はプロセスを起動せず終了する。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(path))
    try:
        lock.acquire(timeout=0)
    except Timeout:
        return None
    return lock


def main() -> None:
    configure_logging()
    lock = try_acquire_singleton_lock(SINGLETON_LOCK_PATH)
    if lock is None:
        logger.info("既に起動中のため終了します")
        return

    try:
        init_db()
        Supervisor().run()
    finally:
        lock.release()


if __name__ == "__main__":
    main()
