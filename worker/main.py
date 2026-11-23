import asyncio
import logging
import os
import threading
import time
from collections.abc import Callable
from datetime import datetime

from claude_agent_sdk import RateLimitEvent

from core.attachments import build_instruction_prompt, list_attachments
from core.claude_client import run_claude
from core.config import settings
from core.db import SessionLocal, init_db
from core.execution_events import record_event
from core.git_client import append_instruction_history, push_branch
from core.github_client import GitHubClientError, mark_pr_ready
from core.idea_queue import claim_next_idea_job, recover_stale_idea_jobs
from core.lifecycle import LifecycleState
from core.logging_config import configure_logging
from core.job_queue import (
    ExecutionJobStatus,
    WorkerState,
    claim_next_job,
    cleanup_stale_workers,
    finish_job,
    heartbeat_job,
    make_process_identifier,
    recover_stale_jobs,
    register_worker,
    requeue_rate_limited_jobs,
    set_worker_state,
)
from core.models import ExecutionJob, Project, Subtask
from core.rate_limits import blocked_until, is_rate_limit_error, record_rate_limit
from core.reports import save_report
from worker.idea_runner import process_idea_job

# python -m worker.main で起動すると__name__が__main__になるため、名前を固定する
logger = logging.getLogger("worker.main")


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
        if isinstance(message, RateLimitEvent):
            record_rate_limit(message.rate_limit_info)

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


def _finalize_success(
    job_id: int, subtask: Subtask, project: Project, worktree_path: str, result_text: str
) -> tuple[str, str | None]:
    """Claude実行後の後処理を行い、ジョブの終了状態と失敗理由を返す

    Draft解除に失敗した場合、Claudeの作業結果は残っているためneeds_attentionとする。
    """
    html_path = save_report(job_id, worktree_path, summary=result_text or "")
    if html_path is None:
        record_event(job_id, event_type="warning", content=".claude-tower/report.htmlが見つからない")

    if not subtask.github_pr_number:
        return ExecutionJobStatus.SUCCEEDED, None
    try:
        mark_pr_ready(project.github_repo, subtask.github_pr_number)
    except GitHubClientError as exc:
        message = f"PRのDraft解除に失敗: {exc}"
        record_event(job_id, event_type="error", content=message)
        return ExecutionJobStatus.NEEDS_ATTENTION, message
    with SessionLocal() as session:
        db_subtask = session.get(Subtask, subtask.id)
        db_subtask.lifecycle_state = LifecycleState.RESOLVED
        session.commit()
    return ExecutionJobStatus.SUCCEEDED, None


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
    status, error_message = _finalize_success(job_id, subtask, project, worktree_path, result_text or "")
    finish_job(job_id, status=status, exit_code=0, error_message=error_message)
    logger.info("job %s 完了(%s): %s", job_id, status, result_text)


def _load_subtask_and_project(subtask_id: int) -> tuple[Subtask, Project]:
    with SessionLocal() as session:
        subtask = session.get(Subtask, subtask_id)
        project = session.get(Project, subtask.project_id)
        session.expunge(subtask)
        session.expunge(project)
    return subtask, project


def process_job(job: dict, worker_id: int) -> None:
    """実装ジョブを1件実行する

    Claudeの利用上限による失敗は、failedと区別してrate_limitedにする。
    """
    job_id = job["job_id"]
    logger.info("job %s (subtask %s) を実行開始", job_id, job["subtask_id"])
    set_worker_state(worker_id, state=WorkerState.BUSY, current_job_id=job_id)

    subtask, project = _load_subtask_and_project(job["subtask_id"])
    record_event(job_id, event_type="instruction", content=subtask.instruction)

    try:
        _run_with_heartbeat(job_id, worker_id, lambda: _execute_job(job_id, subtask, project))
    except Exception as exc:  # noqa: BLE001
        record_event(job_id, event_type="error", content=str(exc))
        status = (
            ExecutionJobStatus.RATE_LIMITED
            if is_rate_limit_error(str(exc))
            else ExecutionJobStatus.FAILED
        )
        finish_job(job_id, status=status, exit_code=1, error_message=str(exc))
        logger.warning("job %s 失敗（%s）: %s", job_id, status, exc)


def _cleanup_stale_records() -> None:
    recovered = recover_stale_jobs(settings.job_stale_timeout_seconds)
    if recovered:
        logger.warning("要確認にしたジョブ: %s", recovered)

    recovered_ideas = recover_stale_idea_jobs(settings.job_stale_timeout_seconds)
    if recovered_ideas:
        logger.warning("要確認にしたアイデア出しジョブ: %s", recovered_ideas)

    removed_workers = cleanup_stale_workers(settings.worker_offline_timeout_seconds)
    if removed_workers:
        logger.info("削除したオフラインワーカー行: %s", removed_workers)


def _requeue_rate_limited() -> None:
    requeued = requeue_rate_limited_jobs(settings.rate_limit_retry_delay_seconds)
    if requeued:
        logger.info("利用上限から再投入したジョブ: %s", requeued)


_notified_resets_at: int | None = None


def _is_rate_limited() -> bool:
    """利用上限中ならTrueを返す

    上限中でなければ、利用上限で中断したジョブを再投入する。
    待機のログはリセット時刻が変わった時のみ出す。
    """
    global _notified_resets_at
    resets_at = blocked_until()
    if resets_at is None:
        _notified_resets_at = None
        _requeue_rate_limited()
        return False
    if resets_at != _notified_resets_at:
        _notified_resets_at = resets_at
        reset_text = datetime.fromtimestamp(resets_at).strftime("%m/%d %H:%M")
        logger.info("利用上限中のためジョブを取得しません（%sにリセット）", reset_text)
    return True


def run_loop(worker_id: int) -> None:
    """ジョブの取得・実行を繰り返す

    自分のワーカー行が削除された場合は、管理対象外になったとみなして終了する。
    再登録はしないため、停止されたワーカーが設定数を超えて残ることはない。
    """
    while True:
        if not set_worker_state(worker_id, state=WorkerState.IDLE, current_job_id=None):
            logger.info("自分のワーカー行が削除されたため終了します")
            return
        _cleanup_stale_records()

        if not _process_next_job(worker_id):
            time.sleep(settings.worker_poll_interval_seconds)


def _process_next_job(worker_id: int) -> bool:
    """待機中のジョブを1件実行する

    実装のジョブを優先し、無ければアイデア出しジョブを実行する。
    実行するジョブが無い場合・利用上限中の場合はFalseを返す。
    """
    if _is_rate_limited():
        return False
    job = claim_next_job(worker_id)
    if job is not None:
        process_job(job, worker_id)
        return True
    idea_job = claim_next_idea_job(worker_id)
    if idea_job is not None:
        process_idea_job(idea_job, worker_id)
        return True
    return False


def main() -> None:
    configure_logging()
    init_db()
    process_identifier = make_process_identifier(os.getpid())
    worker_id = register_worker(process_identifier)
    logger.info("起動しました: %s (id=%s)", process_identifier, worker_id)
    run_loop(worker_id)


if __name__ == "__main__":
    main()
