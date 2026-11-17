import time

from core.config import settings
from core.db import init_db
from worker.pool import WorkerPool, spawn_worker


def main() -> None:
    init_db()
    pool = WorkerPool(settings.worker_count, spawn=spawn_worker)
    pool.start()
    try:
        while True:
            time.sleep(settings.worker_poll_interval_seconds)
            pool.maintain()
    except KeyboardInterrupt:
        pool.stop()


if __name__ == "__main__":
    main()
