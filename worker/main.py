import os
import time
import uuid

from core.config import settings
from core.db import init_db
from core.job_queue import claim_next_job, finish_job, register_worker, set_worker_state


def process_job(job: dict, worker_id: int) -> None:
    print(f"[worker] job {job['job_id']} (subtask {job['subtask_id']}) を実行開始")
    set_worker_state(worker_id, state="busy", current_job_id=job["job_id"])
    # Phase 6でClaude実行に置き換える
    finish_job(job["job_id"], status="succeeded", exit_code=0)
    set_worker_state(worker_id, state="idle", current_job_id=None)
    print(f"[worker] job {job['job_id']} 完了")


def main() -> None:
    init_db()
    process_identifier = f"worker-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    worker_id = register_worker(process_identifier)
    print(f"[worker] 起動しました: {process_identifier} (id={worker_id})")

    while True:
        job = claim_next_job(worker_id)
        if job is None:
            time.sleep(settings.worker_poll_interval_seconds)
            continue
        process_job(job, worker_id)


if __name__ == "__main__":
    main()
