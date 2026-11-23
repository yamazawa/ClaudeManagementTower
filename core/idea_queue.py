"""アイデア出しジョブの待ち行列

実行ジョブ（execution_jobs）と同じワーカーが処理する。
1プロジェクトにつき、待機中・実行中のジョブは1件までとする。
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from core.db import SessionLocal, engine
from core.models import IdeaJob, Project, Worker


class IdeaJobStatus:
    """アイデア出しジョブの状態

    QUEUED : 待機中
    RUNNING : 実行中
    SUCCEEDED : 完了（提案を保存済み）
    FAILED : 失敗
    NEEDS_ATTENTION : 心拍が途絶えた（要確認）
    RATE_LIMITED : Claudeの利用上限で中断した
    """

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    NEEDS_ATTENTION = "needs_attention"
    RATE_LIMITED = "rate_limited"

    ACTIVE_STATES = (QUEUED, RUNNING)


_CLAIM_SQL = text(
    """
    UPDATE idea_jobs
    SET status = 'running'
    WHERE id = (
        SELECT id FROM idea_jobs
        WHERE status = 'queued'
        ORDER BY queued_at
        LIMIT 1
    )
    RETURNING id, project_id, focus
    """
)


class IdeaProjectNotFound(Exception):
    pass


class IdeaJobAlreadyActive(Exception):
    pass


def job_to_dict(job: IdeaJob) -> dict:
    return {
        "id": job.id,
        "project_id": job.project_id,
        "status": job.status,
        "focus": job.focus,
        "queued_at": job.queued_at,
        "started_at": job.started_at,
        "ended_at": job.ended_at,
        "worker_id": job.worker_id,
        "result_summary": job.result_summary,
        "error_message": job.error_message,
    }


def enqueue_idea_job(project_id: int, focus: str = "", session_factory: sessionmaker = SessionLocal) -> dict:
    """アイデア出しジョブを投入する

    同じプロジェクトで待機中・実行中のジョブがあれば重ねて投入しない。
    focusはアイデアを出してほしい観点で、前後の空白を除いて保存する。
    """
    with session_factory() as session:
        if session.get(Project, project_id) is None:
            raise IdeaProjectNotFound("project not found")
        active = (
            session.query(IdeaJob)
            .filter(IdeaJob.project_id == project_id, IdeaJob.status.in_(IdeaJobStatus.ACTIVE_STATES))
            .first()
        )
        if active is not None:
            raise IdeaJobAlreadyActive("アイデア出しを実行中です")
        job = IdeaJob(project_id=project_id, status=IdeaJobStatus.QUEUED, focus=focus.strip())
        session.add(job)
        session.commit()
        return job_to_dict(job)


def latest_idea_job(project_id: int, session_factory: sessionmaker = SessionLocal) -> dict | None:
    with session_factory() as session:
        job = (
            session.query(IdeaJob)
            .filter(IdeaJob.project_id == project_id)
            .order_by(IdeaJob.id.desc())
            .first()
        )
        return job_to_dict(job) if job else None


def claim_next_idea_job(worker_id: int, bind=engine, session_factory: sessionmaker = SessionLocal):
    with bind.begin() as conn:
        row = conn.execute(_CLAIM_SQL).fetchone()
    if row is None:
        return None

    now = datetime.now(timezone.utc)
    with session_factory() as session:
        job = session.get(IdeaJob, row.id)
        job.worker_id = worker_id
        job.started_at = now
        job.heartbeat_at = now
        session.commit()
    return {"idea_job_id": row.id, "project_id": row.project_id, "focus": row.focus or ""}


def heartbeat_idea_job(idea_job_id: int, worker_id: int, session_factory: sessionmaker = SessionLocal) -> None:
    now = datetime.now(timezone.utc)
    with session_factory() as session:
        job = session.get(IdeaJob, idea_job_id)
        worker = session.get(Worker, worker_id)
        if job is not None:
            job.heartbeat_at = now
        if worker is not None:
            worker.heartbeat_at = now
        session.commit()


def finish_idea_job(
    idea_job_id: int,
    status: str,
    claude_session_id: str | None = None,
    result_summary: str | None = None,
    error_message: str | None = None,
    session_factory: sessionmaker = SessionLocal,
) -> None:
    with session_factory() as session:
        job = session.get(IdeaJob, idea_job_id)
        job.status = status
        job.claude_session_id = claude_session_id
        job.result_summary = result_summary
        job.error_message = error_message
        job.ended_at = datetime.now(timezone.utc)
        session.commit()


def recover_stale_idea_jobs(timeout_seconds: int, session_factory: sessionmaker = SessionLocal) -> list[int]:
    threshold = datetime.now(timezone.utc) - timedelta(seconds=timeout_seconds)
    with session_factory() as session:
        stale_jobs = (
            session.query(IdeaJob)
            .filter(IdeaJob.status == IdeaJobStatus.RUNNING, IdeaJob.heartbeat_at < threshold)
            .all()
        )
        for job in stale_jobs:
            job.status = IdeaJobStatus.NEEDS_ATTENTION
        session.commit()
        return [job.id for job in stale_jobs]
