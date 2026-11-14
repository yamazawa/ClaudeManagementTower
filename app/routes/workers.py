from fastapi import APIRouter

from core.db import SessionLocal
from core.models import Worker

router = APIRouter(prefix="/api/workers")


@router.get("")
def get_workers():
    with SessionLocal() as session:
        workers = session.query(Worker).all()
        return [
            {
                "id": w.id,
                "process_identifier": w.process_identifier,
                "state": w.state,
                "heartbeat_at": w.heartbeat_at,
                "current_job_id": w.current_job_id,
            }
            for w in workers
        ]
