from fastapi import APIRouter, HTTPException

from core.db import SessionLocal
from core.models import ExecutionJob

router = APIRouter(prefix="/api/jobs")


@router.get("/{job_id}")
def get_job(job_id: int):
    with SessionLocal() as session:
        job = session.get(ExecutionJob, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        return {
            "id": job.id,
            "subtask_id": job.subtask_id,
            "status": job.status,
            "queued_at": job.queued_at,
            "started_at": job.started_at,
            "ended_at": job.ended_at,
            "exit_code": job.exit_code,
            "worker_id": job.worker_id,
        }
