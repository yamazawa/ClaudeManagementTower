import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from core.db import SessionLocal, engine
from core.models import ExecutionJob, Worker


class ExecutionJobStatus:
    """実装ジョブの状態

    QUEUED : 待機中
    RUNNING : 実行中
    SUCCEEDED : 完了
    FAILED : 失敗
    NEEDS_ATTENTION : 要確認（心拍途絶・PR更新失敗など）
    RATE_LIMITED : Claudeの利用上限で中断した（リセット後に自動で再投入する）
    """

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    NEEDS_ATTENTION = "needs_attention"
    RATE_LIMITED = "rate_limited"

    # 実行中とみなす状態（実行中はマージさせない）
    ACTIVE_STATES = (QUEUED, RUNNING)


class WorkerState:
    """ワーカーの状態

    IDLE : 待機中
    BUSY : ジョブ実行中
    """

    IDLE = "idle"
    BUSY = "busy"


_CLAIM_SQL = text(
    """
    UPDATE execution_jobs
    SET status = :running
    WHERE id = (
        SELECT ej.id FROM execution_jobs ej
        WHERE ej.status = :queued
          AND NOT EXISTS (
            SELECT 1 FROM execution_jobs ej2
            WHERE ej2.subtask_id = ej.subtask_id
              AND ej2.status = :running
          )
        ORDER BY ej.queued_at
        LIMIT 1
    )
    RETURNING id, subtask_id
    """
).bindparams(running=ExecutionJobStatus.RUNNING, queued=ExecutionJobStatus.QUEUED)


# ハートビートが途絶えて要確認にしたジョブの失敗理由
STALE_JOB_ERROR_MESSAGE = "ワーカーからの応答が途絶えたため中断しました"

_PROCESS_IDENTIFIER_PREFIX = "worker"


def make_process_identifier(pid: int) -> str:
    return f"{_PROCESS_IDENTIFIER_PREFIX}-{pid}-{uuid.uuid4().hex[:8]}"


def parse_worker_pid(process_identifier: str) -> int | None:
    """ワーカー識別子からPIDを取り出す

    make_process_identifierの形式でない場合はNoneを返す。
    """
    parts = process_identifier.split("-")
    if len(parts) != 3 or parts[0] != _PROCESS_IDENTIFIER_PREFIX or not parts[1].isdigit():
        return None
    return int(parts[1])


def list_live_worker_pids(
    timeout_seconds: int,
    session_factory: sessionmaker = SessionLocal,
) -> list[int]:
    """心拍が途絶えていないワーカーのPID一覧を返す"""
    threshold = datetime.now(timezone.utc) - timedelta(seconds=timeout_seconds)
    with session_factory() as session:
        workers = session.query(Worker).filter(Worker.heartbeat_at >= threshold).all()
        pids = [parse_worker_pid(worker.process_identifier) for worker in workers]
    return [pid for pid in pids if pid is not None]


def delete_all_workers(session_factory: sessionmaker = SessionLocal) -> int:
    with session_factory() as session:
        deleted = session.query(Worker).delete()
        session.commit()
    return deleted


def register_worker(process_identifier: str, session_factory: sessionmaker = SessionLocal) -> int:
    now = datetime.now(timezone.utc)
    with session_factory() as session:
        worker = (
            session.query(Worker).filter_by(process_identifier=process_identifier).first()
        )
        if worker is None:
            worker = Worker(
                process_identifier=process_identifier, state=WorkerState.IDLE, heartbeat_at=now
            )
            session.add(worker)
        else:
            worker.state = WorkerState.IDLE
            worker.heartbeat_at = now
        session.commit()
        session.refresh(worker)
        return worker.id


def claim_next_job(worker_id: int, bind=engine, session_factory: sessionmaker = SessionLocal):
    with bind.begin() as conn:
        row = conn.execute(_CLAIM_SQL).fetchone()
    if row is None:
        return None

    now = datetime.now(timezone.utc)
    with session_factory() as session:
        job = session.get(ExecutionJob, row.id)
        job.worker_id = worker_id
        job.claimed_at = now
        job.started_at = now
        job.heartbeat_at = now
        session.commit()

    return {"job_id": row.id, "subtask_id": row.subtask_id}


def heartbeat_job(
    job_id: int,
    worker_id: int,
    session_factory: sessionmaker = SessionLocal,
) -> None:
    now = datetime.now(timezone.utc)
    with session_factory() as session:
        job = session.get(ExecutionJob, job_id)
        worker = session.get(Worker, worker_id)
        if job is not None:
            job.heartbeat_at = now
        if worker is not None:
            worker.heartbeat_at = now
        session.commit()


def recover_stale_jobs(
    timeout_seconds: int,
    session_factory: sessionmaker = SessionLocal,
) -> list[int]:
    threshold = datetime.now(timezone.utc) - timedelta(seconds=timeout_seconds)
    with session_factory() as session:
        stale_jobs = (
            session.query(ExecutionJob)
            .filter(
                ExecutionJob.status == ExecutionJobStatus.RUNNING,
                ExecutionJob.heartbeat_at < threshold,
            )
            .all()
        )
        recovered_ids = [job.id for job in stale_jobs]
        for job in stale_jobs:
            job.status = ExecutionJobStatus.NEEDS_ATTENTION
            job.error_message = STALE_JOB_ERROR_MESSAGE
        session.commit()
    return recovered_ids


def _has_newer_job(session, job: ExecutionJob) -> bool:
    return (
        session.query(ExecutionJob)
        .filter(ExecutionJob.subtask_id == job.subtask_id, ExecutionJob.id > job.id)
        .first()
        is not None
    )


def requeue_rate_limited_jobs(
    retry_delay_seconds: int,
    session_factory: sessionmaker = SessionLocal,
) -> list[int]:
    """利用上限で中断したジョブを待機中に戻す

    中断から一定時間が過ぎたジョブのみ対象とする。
    同じサブタスクで後から再実行されたジョブは対象外とする。
    """
    threshold = datetime.now(timezone.utc) - timedelta(seconds=retry_delay_seconds)
    with session_factory() as session:
        candidates = (
            session.query(ExecutionJob)
            .filter(
                ExecutionJob.status == ExecutionJobStatus.RATE_LIMITED,
                ExecutionJob.ended_at < threshold,
            )
            .all()
        )
        targets = [job for job in candidates if not _has_newer_job(session, job)]
        for job in targets:
            job.status = ExecutionJobStatus.QUEUED
            job.exit_code = None
            job.ended_at = None
            job.error_message = None
        session.commit()
        return [job.id for job in targets]


def cleanup_stale_workers(
    timeout_seconds: int,
    session_factory: sessionmaker = SessionLocal,
) -> list[int]:
    threshold = datetime.now(timezone.utc) - timedelta(seconds=timeout_seconds)
    with session_factory() as session:
        stale_workers = session.query(Worker).filter(Worker.heartbeat_at < threshold).all()
        removed_ids = [worker.id for worker in stale_workers]
        for worker in stale_workers:
            session.delete(worker)
        session.commit()
    return removed_ids


def finish_job(
    job_id: int,
    status: str,
    exit_code: int,
    error_message: str | None = None,
    session_factory: sessionmaker = SessionLocal,
) -> None:
    with session_factory() as session:
        job = session.get(ExecutionJob, job_id)
        job.status = status
        job.exit_code = exit_code
        job.error_message = error_message
        job.ended_at = datetime.now(timezone.utc)
        session.commit()


def set_worker_state(
    worker_id: int,
    state: str,
    current_job_id: int | None,
    session_factory: sessionmaker = SessionLocal,
) -> bool:
    with session_factory() as session:
        worker = session.get(Worker, worker_id)
        if worker is None:
            return False
        worker.state = state
        worker.current_job_id = current_job_id
        worker.heartbeat_at = datetime.now(timezone.utc)
        session.commit()
        return True
