from sqlalchemy.orm import sessionmaker

from core.db import init_db, make_engine
from core.models import Project


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
