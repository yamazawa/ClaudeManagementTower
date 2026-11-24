import ast
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker

from app.routes import error_messages as messages
from app.routes import jobs, projects, subtasks
from core.db import init_db, make_engine

ROUTES_DIR = Path(__file__).resolve().parent.parent / "app" / "routes"


@pytest.fixture
def session_factory(tmp_path, monkeypatch):
    engine = make_engine(str(tmp_path / "test.db"))
    init_db(bind=engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(jobs, "SessionLocal", factory)
    return factory


def _literal_details(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        ast.unparse(keyword.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "HTTPException"
        for keyword in node.keywords
        if keyword.arg == "detail" and isinstance(keyword.value, (ast.Constant, ast.JoinedStr))
    ]


def test_routes_do_not_hardcode_error_details():
    found = {path.name: _literal_details(path) for path in ROUTES_DIR.glob("*.py")}

    assert {name: details for name, details in found.items() if details} == {}


def test_job_not_found_detail_is_japanese(session_factory):
    with pytest.raises(HTTPException) as error:
        jobs.get_job(999)

    assert error.value.detail == messages.JOB_NOT_FOUND


@pytest.mark.parametrize("module", [projects, subtasks])
def test_project_404_uses_shared_message(session_factory, module):
    with session_factory() as session, pytest.raises(HTTPException) as error:
        module._get_project_or_404(session, 999)

    assert error.value.detail == messages.PROJECT_NOT_FOUND
