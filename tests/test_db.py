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
        assert conn.exec_driver_sql("SELECT idea_session_id FROM idea_jobs WHERE id = 1").scalar() is None


def test_init_db_adds_title_and_state_to_existing_cli_sessions(tmp_path):
    engine = make_engine(str(tmp_path / "test.db"))
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE cli_sessions (id INTEGER PRIMARY KEY, project_id INTEGER, status VARCHAR)")
        conn.exec_driver_sql("INSERT INTO cli_sessions (id, project_id, status) VALUES (1, 1, 'idle')")

    init_db(bind=engine)

    with engine.connect() as conn:
        row = conn.exec_driver_sql("SELECT title, state FROM cli_sessions WHERE id = 1").one()
    assert tuple(row) == ("", "open")


def test_init_db_adds_display_name_and_description_to_existing_projects(tmp_path):
    engine = make_engine(str(tmp_path / "test.db"))
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE projects (id INTEGER PRIMARY KEY, name VARCHAR, github_repo VARCHAR,"
            " repo_path VARCHAR, default_branch VARCHAR, created_at DATETIME)"
        )
        conn.exec_driver_sql("INSERT INTO projects (id, name) VALUES (1, 'p')")

    init_db(bind=engine)

    with engine.connect() as conn:
        row = conn.exec_driver_sql("SELECT display_name, description FROM projects WHERE id = 1").one()
    assert tuple(row) == ("", "")


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
