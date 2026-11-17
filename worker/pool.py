"""ワーカープロセス群の管理

設定数のワーカープロセスを直接の子プロセスとして起動し、個数を維持する。
起動時は登録済みの既存ワーカーを停止し、取り残されたプロセスを残さない。
"""

import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import sessionmaker

from core.config import settings
from core.db import SessionLocal
from core.job_queue import delete_all_workers, list_live_worker_pids

WORKER_ARGS = ["-u", "-m", "worker.main"]
STOP_TIMEOUT_SECONDS = 10


def spawn_worker(env: dict[str, str] | None = None) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, *WORKER_ARGS], env=env)


def kill_pid(pid: int) -> None:
    """PIDを指定してプロセスを終了する

    WindowsではTerminateProcessとなる。
    既に終了済み・権限不足の場合は無視する。
    """
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass


def stop_process(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=STOP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


@dataclass
class _Slot:
    process: subprocess.Popen
    spawned_at: float


class WorkerPool:
    """設定数のワーカープロセスを維持するプール

    終了したワーカーはmaintainで再起動し、常に設定数を保つ。
    start・stopの際は登録済みの全ワーカーを停止し、ワーカー行を削除する。
    """

    def __init__(
        self,
        count: int,
        spawn: Callable[[], subprocess.Popen],
        kill: Callable[[int], None] = kill_pid,
        session_factory: sessionmaker = SessionLocal,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.count = count
        self._spawn = spawn
        self._kill = kill
        self._session_factory = session_factory
        self._clock = clock
        self._slots: list[_Slot] = []

    def is_running(self) -> bool:
        return bool(self._slots)

    def processes(self) -> list[subprocess.Popen]:
        return [slot.process for slot in self._slots]

    def start(self) -> None:
        self.stop()
        print(f"[pool] worker.count={self.count}個のワーカーを起動します")
        self._slots = [self._new_slot() for _ in range(self.count)]

    def stop(self) -> None:
        for slot in self._slots:
            stop_process(slot.process)
        self._slots = []
        self._stop_registered_workers()

    def maintain(self) -> None:
        """終了したワーカーを再起動する

        起動直後に終了を繰り返す場合に備え、前回起動から一定時間は再起動しない。
        """
        now = self._clock()
        for index, slot in enumerate(self._slots):
            if slot.process.poll() is None:
                continue
            if now - slot.spawned_at < settings.worker_respawn_delay_seconds:
                continue
            print(f"[pool] 終了したワーカー(slot {index})を再起動します")
            self._slots[index] = self._new_slot()

    def _new_slot(self) -> _Slot:
        return _Slot(process=self._spawn(), spawned_at=self._clock())

    def _stop_registered_workers(self) -> None:
        """登録済みで稼働中のワーカーを終了し、ワーカー行を全削除する

        過去の起動で取り残されたワーカーや個別起動したワーカーも対象となる。
        """
        pids = list_live_worker_pids(
            settings.worker_offline_timeout_seconds, session_factory=self._session_factory
        )
        foreign_pids = [pid for pid in pids if pid != os.getpid()]
        for pid in foreign_pids:
            self._kill(pid)
        if foreign_pids:
            print(f"[pool] 登録済みのワーカーを停止しました: {foreign_pids}")
        delete_all_workers(session_factory=self._session_factory)
