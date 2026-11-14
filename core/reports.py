from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import sessionmaker

from core.db import SessionLocal
from core.models import Report

REPORTS_DIR = Path("reports")


def save_report(
    job_id: int,
    worktree_path: str,
    summary: str,
    session_factory: sessionmaker = SessionLocal,
) -> str | None:
    source = Path(worktree_path) / ".claude-tower" / "report.html"
    if not source.exists():
        return None

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    html_path = REPORTS_DIR / f"job-{job_id}.html"
    html_path.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    with session_factory() as session:
        session.add(
            Report(
                job_id=job_id,
                html_path=str(html_path),
                summary=summary[:2000],
                created_at=datetime.now(timezone.utc),
            )
        )
        session.commit()

    return str(html_path)
