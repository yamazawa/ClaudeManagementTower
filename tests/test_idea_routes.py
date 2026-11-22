import pytest
from fastapi import HTTPException

from app.routes import ideas
from core.idea_queue import IdeaJobAlreadyActive, IdeaProjectNotFound
from core.ideas import IdeaAlreadyDecided, IdeaNotFound, IdeaStatus


def _raiser(exc):
    def fail(*args, **kwargs):
        raise exc

    return fail


@pytest.mark.parametrize(("exc", "status"), [(IdeaProjectNotFound("x"), 404), (IdeaJobAlreadyActive("x"), 409)])
def test_run_maps_errors(monkeypatch, exc, status):
    monkeypatch.setattr(ideas, "enqueue_idea_job", _raiser(exc))

    with pytest.raises(HTTPException) as error:
        ideas.run_idea_generation(1)
    assert error.value.status_code == status


def test_run_returns_queued_job(monkeypatch):
    monkeypatch.setattr(ideas, "enqueue_idea_job", lambda project_id: {"id": 4, "project_id": project_id})

    assert ideas.run_idea_generation(2) == {"id": 4, "project_id": 2}


@pytest.mark.parametrize(
    ("tab", "statuses"),
    [("pending", IdeaStatus.PENDING_STATES), ("rejected", IdeaStatus.REJECTED_STATES), ("all", None)],
)
def test_get_ideas_filters_by_tab(monkeypatch, tab, statuses):
    calls = []
    monkeypatch.setattr(ideas, "list_ideas", lambda project_id, s: calls.append((project_id, s)) or [])

    ideas.get_ideas(1, tab)

    assert calls == [(1, statuses)]


@pytest.mark.parametrize(("exc", "status"), [(IdeaNotFound("x"), 404), (IdeaAlreadyDecided("x"), 409)])
def test_reject_maps_errors(monkeypatch, exc, status):
    monkeypatch.setattr(ideas, "reject_idea", _raiser(exc))

    with pytest.raises(HTTPException) as error:
        ideas.post_reject_idea(1, ideas.RejectIdeaRequest(reason="r"))
    assert error.value.status_code == status


def test_routes_are_registered():
    from app.main import app

    paths = app.openapi()["paths"]
    assert "/api/projects/{project_id}/ideas/run" in paths
    assert "/api/ideas/{idea_id}/reject" in paths
