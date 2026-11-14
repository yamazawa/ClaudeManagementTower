from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from core.config import settings
from core.models import Base


def _apply_sqlite_pragma(dbapi_connection, connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


def make_engine(database_path: str):
    engine = create_engine(f"sqlite:///{database_path}")
    event.listen(engine, "connect", _apply_sqlite_pragma)
    return engine


engine = make_engine(settings.database_path)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db(bind=engine) -> None:
    Base.metadata.create_all(bind=bind)
