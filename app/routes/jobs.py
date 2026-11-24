from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from app.routes import error_messages as messages
from core.db import SessionLocal
from core.models import ExecutionEvent, ExecutionJob, Report

router = APIRouter(prefix="/api/jobs")

REPORT_CSP = "default-src 'none'; style-src 'unsafe-inline'"


@router.get("/{job_id}")
def get_job(job_id: int):
    with SessionLocal() as session:
        job = session.get(ExecutionJob, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=messages.JOB_NOT_FOUND)
        return {
            "id": job.id,
            "subtask_id": job.subtask_id,
            "status": job.status,
            "queued_at": job.queued_at,
            "started_at": job.started_at,
            "ended_at": job.ended_at,
            "exit_code": job.exit_code,
            "worker_id": job.worker_id,
            "claude_session_id": job.claude_session_id,
            "error_message": job.error_message,
        }


@router.get("/{job_id}/events")
def get_job_events(job_id: int):
    with SessionLocal() as session:
        events = (
            session.query(ExecutionEvent)
            .filter_by(job_id=job_id)
            .order_by(ExecutionEvent.sequence_no)
            .all()
        )
        return [
            {
                "sequence_no": e.sequence_no,
                "event_type": e.event_type,
                "content": e.content,
                "created_at": e.created_at,
            }
            for e in events
        ]


@router.get("/{job_id}/report")
def get_job_report(job_id: int):
    with SessionLocal() as session:
        report = session.query(Report).filter_by(job_id=job_id).first()
        if report is None:
            raise HTTPException(status_code=404, detail=messages.REPORT_NOT_FOUND)
        html = Path(report.html_path).read_text(encoding="utf-8")
        return HTMLResponse(content=html, headers={"Content-Security-Policy": REPORT_CSP})
