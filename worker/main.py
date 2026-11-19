import asyncio
import os
import threading
import time
from collections.abc import Callable

from core.attachments import build_instruction_prompt, list_attachments
from core.claude_client import run_claude
from core.config import settings
from core.db import SessionLocal, init_db
from core.execution_events import record_event
from core.git_client import append_instruction_history, push_branch
from core.github_client import mark_pr_ready
from core.lifecycle import LifecycleState
from core.job_queue import (
    claim_next_job,
    cleanup_stale_workers,
    finish_job,
    heartbeat_job,
    make_process_identifier,
    recover_stale_jobs,
    register_worker,
    set_worker_state,
)
from core.models import ExecutionJob, Project, Subtask
from core.reports import save_report


def _previous_session_id(subtask_id: int, current_job_id: int) -> str | None:
    with SessionLocal() as session:
        previous = (
            session.query(ExecutionJob)
            .filter(
                ExecutionJob.subtask_id == subtask_id,
                ExecutionJob.id != current_job_id,
                ExecutionJob.claude_session_id.isnot(None),
            )
            .order_by(ExecutionJob.id.desc())
            .first()
        )
        return previous.claude_session_id if previous else None


def _run_claude_for_job(
    job_id: int,
    worktree_path: str,
    instruction: str,
    resume: str | None,
) -> tuple[str | None, str | None]:
    def on_message(message: object) -> None:
        record_event(job_id, event_type=type(message).__name__, content=repr(message)[:4000])

    return asyncio.run(run_claude(instruction, worktree_path, resume=resume, on_message=on_message))


def _run_with_heartbeat(job_id: int, worker_id: int, action: Callable[[], None]) -> None:
    stop_event = threading.Event()

    def heartbeat_loop() -> None:
        while not stop_event.wait(settings.job_heartbeat_interval_seconds):
            heartbeat_job(job_id, worker_id)

    thread = threading.Thread(target=heartbeat_loop, daemon=True)
    thread.start()
    try:
        action()
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
            db_subtask.lifecycle_state = LifecycleState.RESOLVED
            session.commit()


def _execute_job(job_id: int, subtask: Subtask, project: Project) -> None:
    worktree_path = f"{settings.worktree_base_dir}/{subtask.branch_name}"
    resume = _previous_session_id(subtask.id, job_id)
    append_instruction_history(worktree_path, subtask.instruction)
    push_branch(worktree_path, subtask.branch_name)

    prompt = build_instruction_prompt(subtask.instruction, list_attachments(worktree_path))
    session_id, result_text = _run_claude_for_job(job_id, worktree_path, prompt, resume)
    with SessionLocal() as session:
        db_job = session.get(ExecutionJob, job_id)
        db_job.claude_session_id = session_id
        session.commit()
    _finalize_success(job_id, subtask, project, worktree_path, result_text or "")
    finish_job(job_id, status="succeeded", exit_code=0)
    print(f"[worker] job {job_id} 完了: {result_text}")


def process_job(job: dict, worker_id: int) -> None:
    job_id = job["job_id"]
    print(f"[worker] job {job_id} (subtask {job['subtask_id']}) を実行開始")
    set_worker_state(worker_id, state="busy", current_job_id=job_id)

    with SessionLocal() as session:
        subtask = session.get(Subtask, job["subtask_id"])
        project = session.get(Project, subtask.project_id)
        session.expunge(subtask)
        session.expunge(project)
    record_event(job_id, event_type="instruction", content=subtask.instruction)

    try:
        _run_with_heartbeat(job_id, worker_id, lambda: _execute_job(job_id, subtask, project))
    except Exception as exc:  # noqa: BLE001
        record_event(job_id, event_type="error", content=str(exc))
        finish_job(job_id, status="failed", exit_code=1)
        print(f"[worker] job {job_id} 失敗: {exc}")


def _cleanup_stale_records() -> None:
    recovered = recover_stale_jobs(settings.job_stale_timeout_seconds)
    if recovered:
        print(f"[worker] 要確認にしたジョブ: {recovered}")

    removed_workers = cleanup_stale_workers(settings.worker_offline_timeout_seconds)
    if removed_workers:
        print(f"[worker] 削除したオフラインワーカー行: {removed_workers}")


def run_loop(worker_id: int) -> None:
    """ジョブの取得・実行を繰り返す

    自分のワーカー行が削除された場合は、管理対象外になったとみなして終了する。
    再登録はしないため、停止されたワーカーが設定数を超えて残ることはない。
    """
    while True:
        if not set_worker_state(worker_id, state="idle", current_job_id=None):
            print("[worker] 自分のワーカー行が削除されたため終了します")
            return
        _cleanup_stale_records()

        job = claim_next_job(worker_id)
        if job is None:
            time.sleep(settings.worker_poll_interval_seconds)
            continue
        process_job(job, worker_id)


def main() -> None:
    init_db()
    process_identifier = make_process_identifier(os.getpid())
    worker_id = register_worker(process_identifier)
    print(f"[worker] 起動しました: {process_identifier} (id={worker_id})")
    run_loop(worker_id)


if __name__ == "__main__":
    main()
