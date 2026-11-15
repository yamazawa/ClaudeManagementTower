import asyncio
import os
import threading
import time
import uuid

from core.claude_client import run_claude
from core.config import settings
from core.db import SessionLocal, init_db
from core.execution_events import record_event
from core.github_client import mark_pr_ready
from core.job_queue import (
    claim_next_job,
    finish_job,
    heartbeat_job,
    recover_stale_jobs,
    register_worker,
    set_worker_state,
)
from core.models import ExecutionJob, Project, Subtask
from core.reports import save_report


def _run_claude_for_job(job_id: int, worktree_path: str, instruction: str) -> tuple[str | None, str | None]:
    def on_message(message: object) -> None:
        record_event(job_id, event_type=type(message).__name__, content=repr(message)[:4000])

    return asyncio.run(run_claude(instruction, worktree_path, on_message=on_message))


def _run_with_heartbeat(job_id: int, worker_id: int, worktree_path: str, instruction: str):
    stop_event = threading.Event()

    def heartbeat_loop() -> None:
        while not stop_event.wait(settings.job_heartbeat_interval_seconds):
            heartbeat_job(job_id, worker_id)

    thread = threading.Thread(target=heartbeat_loop, daemon=True)
    thread.start()
    try:
        return _run_claude_for_job(job_id, worktree_path, instruction)
    finally:
        stop_event.set()
        thread.join()


def _finalize_success(job_id: int, subtask: Subtask, project: Project, worktree_path: str, result_text: str) -> None:
    html_path = save_report(job_id, worktree_path, summary=result_text or "")
    if html_path is None:
        record_event(job_id, event_type="warning", content=".claude-tower/report.htmlが見つからない")

    if subtask.github_pr_number:
        mark_pr_ready(project.github_repo, subtask.github_pr_number)
        with SessionLocal() as session:
            db_subtask = session.get(Subtask, subtask.id)
            db_subtask.lifecycle_state = "in_review"
            session.commit()


def process_job(job: dict, worker_id: int) -> None:
    print(f"[worker] job {job['job_id']} (subtask {job['subtask_id']}) を実行開始")
    set_worker_state(worker_id, state="busy", current_job_id=job["job_id"])

    with SessionLocal() as session:
        subtask = session.get(Subtask, job["subtask_id"])
        project = session.get(Project, subtask.project_id)
        session.expunge(subtask)
        session.expunge(project)
    worktree_path = f"{settings.worktree_base_dir}/{subtask.branch_name}"

    try:
        session_id, result_text = _run_with_heartbeat(
            job["job_id"], worker_id, worktree_path, subtask.instruction
        )
        with SessionLocal() as session:
            db_job = session.get(ExecutionJob, job["job_id"])
            db_job.claude_session_id = session_id
            session.commit()
        _finalize_success(job["job_id"], subtask, project, worktree_path, result_text or "")
        finish_job(job["job_id"], status="succeeded", exit_code=0)
        print(f"[worker] job {job['job_id']} 完了: {result_text}")
    except Exception as exc:  # noqa: BLE001
        record_event(job["job_id"], event_type="error", content=str(exc))
        finish_job(job["job_id"], status="failed", exit_code=1)
        print(f"[worker] job {job['job_id']} 失敗: {exc}")

    set_worker_state(worker_id, state="idle", current_job_id=None)


def main() -> None:
    init_db()
    process_identifier = f"worker-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    worker_id = register_worker(process_identifier)
    print(f"[worker] 起動しました: {process_identifier} (id={worker_id})")

    while True:
        recovered = recover_stale_jobs(settings.job_stale_timeout_seconds)
        if recovered:
            print(f"[worker] 要確認にしたジョブ: {recovered}")

        job = claim_next_job(worker_id)
        if job is None:
            set_worker_state(worker_id, state="idle", current_job_id=None)
            time.sleep(settings.worker_poll_interval_seconds)
            continue
        process_job(job, worker_id)


if __name__ == "__main__":
    main()
