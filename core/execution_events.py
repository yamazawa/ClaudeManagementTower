from datetime import datetime, timezone

from sqlalchemy.orm import sessionmaker

from core.db import SessionLocal
from core.models import ExecutionEvent


def record_event(
    job_id: int,
    event_type: str,
    content: str,
    session_factory: sessionmaker = SessionLocal,
) -> None:
    with session_factory() as session:
        next_seq = session.query(ExecutionEvent).filter_by(job_id=job_id).count() + 1
        session.add(
            ExecutionEvent(
                job_id=job_id,
                sequence_no=next_seq,
                event_type=event_type,
                content=content,
                created_at=datetime.now(timezone.utc),
            )
        )
        session.commit()
