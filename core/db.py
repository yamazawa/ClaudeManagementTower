from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from core.config import settings
from core.models import Base, Project


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


# create_allで追加されない既存テーブルへの後付け列（テーブル名, 列名, 列定義）
ADDED_COLUMNS = [
    ("idea_jobs", "focus", "VARCHAR NOT NULL DEFAULT ''"),
    ("idea_jobs", "idea_session_id", "INTEGER REFERENCES idea_sessions(id)"),
    ("cli_sessions", "title", "VARCHAR NOT NULL DEFAULT ''"),
    ("cli_sessions", "state", "VARCHAR NOT NULL DEFAULT 'open'"),
    ("cli_messages", "attachments", "VARCHAR NOT NULL DEFAULT '[]'"),
]


def _add_missing_columns(bind) -> None:
    """既存テーブルに後付けの列が無ければ追加する

    稼働中の管理塔のDBを作り直さずに起動できるようにする。
    """
    with bind.begin() as conn:
        for table, column, definition in ADDED_COLUMNS:
            existing = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
            if column not in existing:
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db(bind=engine) -> None:
    Base.metadata.create_all(bind=bind)
    _add_missing_columns(bind)


def ensure_default_project() -> None:
    with SessionLocal() as session:
        existing = (
            session.query(Project)
            .filter_by(github_repo=settings.github_target_repo)
            .first()
        )
        if existing is not None:
            return
        session.add(
            Project(
                name=settings.github_target_repo,
                github_repo=settings.github_target_repo,
                repo_path=settings.github_target_repo_path,
                default_branch=settings.github_default_branch,
            )
        )
        session.commit()
