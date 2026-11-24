"""ジョブ実行中のハートビート送信"""

import threading
from collections.abc import Callable

from core.config import settings


def run_with_heartbeat(heartbeat: Callable[[], None], action: Callable[[], None]) -> None:
    """actionの実行中、一定間隔でheartbeatを呼ぶ

    ハートビートは別スレッドで送り、actionの終了（例外含む）で止める。
    """
    stop_event = threading.Event()

    def heartbeat_loop() -> None:
        while not stop_event.wait(settings.job_heartbeat_interval_seconds):
            heartbeat()

    thread = threading.Thread(target=heartbeat_loop, daemon=True)
    thread.start()
    try:
        action()
    finally:
        stop_event.set()
        thread.join()
