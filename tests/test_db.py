from sqlalchemy.orm import sessionmaker

from core.db import init_db, make_engine
from core.models import Project


def test_init_db_adds_missing_columns_to_existing_table(tmp_path):
    engine = make_engine(str(tmp_path / "test.db"))
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE idea_jobs (id INTEGER PRIMARY KEY, project_id INTEGER, status VARCHAR)")
        conn.exec_driver_sql("INSERT INTO idea_jobs (id, project_id, status) VALUES (1, 1, 'succeeded')")

    init_db(bind=engine)
    init_db(bind=engine)

    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT focus FROM idea_jobs WHERE id = 1").scalar() == ""


def test_write_and_read_project(tmp_path):
    engine = make_engine(str(tmp_path / "test.db"))
    init_db(bind=engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        session.add(
            Project(
                name="テストプロジェクト",
                github_repo="yamazawa/claude-tower-test-repo",
                repo_path="C:/git/claude-tower-test-repo",
                default_branch="master",
            )
        )
        session.commit()

    with session_factory() as session:
        project = session.query(Project).one()
        assert project.name == "テストプロジェクト"
        assert project.github_repo == "yamazawa/claude-tower-test-repo"
