from datetime import datetime, timedelta, timezone

from fastapi import APIRouter

from core.config import settings
from core.db import SessionLocal
from core.models import Worker

router = APIRouter(prefix="/api/workers")


@router.get("")
def get_workers():
    threshold = datetime.now(timezone.utc) - timedelta(
        seconds=settings.worker_offline_timeout_seconds
    )
    with SessionLocal() as session:
        workers = session.query(Worker).all()
        return [
            {
                "id": w.id,
                "process_identifier": w.process_identifier,
                "state": w.state,
                "heartbeat_at": w.heartbeat_at,
                "current_job_id": w.current_job_id,
                "is_stale": w.heartbeat_at.replace(tzinfo=timezone.utc) < threshold,
            }
            for w in workers
        ]
