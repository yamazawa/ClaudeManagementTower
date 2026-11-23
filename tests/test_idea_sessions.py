import pytest
from sqlalchemy.orm import sessionmaker

from core import idea_sessions
from core.db import init_db, make_engine
from core.idea_queue import IdeaJobAlreadyActive, IdeaJobStatus, finish_idea_job
from core.ideas import IdeaStatus, save_proposals
from core.models import IdeaJob, Project
from core.repo_items import ItemState, RepoItemClosed, RepoItemInvalid, RepoItemNotFound


@pytest.fixture
def session_factory(tmp_path):
    engine = make_engine(str(tmp_path / "test.db"))
    init_db(bind=engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        session.add(Project(id=1, name="p", github_repo="owner/repo", repo_path="C:/repo", default_branch="master"))
        session.commit()
    return factory


def _create(factory, title="観点A"):
    return idea_sessions.create_session(1, title, session_factory=factory)["id"]


def _proposal(title):
    return {
        "category": "bug",
        "title": title,
        "summary": "",
        "detail": "",
        "rationale": "",
        "related_files": "",
        "related_issue_number": None,
    }


def test_create_session_rejects_empty_title_and_unknown_project(session_factory):
    with pytest.raises(RepoItemInvalid):
        idea_sessions.create_session(1, " ", session_factory=session_factory)
    with pytest.raises(RepoItemNotFound):
        idea_sessions.create_session(9, "観点", session_factory=session_factory)


def test_list_sessions_filters_by_state_with_latest_job(session_factory):
    opened = _create(session_factory)
    closed = _create(session_factory, "観点B")
    idea_sessions.update_session(closed, state=ItemState.CLOSED, session_factory=session_factory)
    job = idea_sessions.run_session(opened, "テスト", session_factory=session_factory)

    listed = idea_sessions.list_sessions(1, ItemState.OPEN, session_factory=session_factory)

    assert [s["id"] for s in listed] == [opened]
    assert listed[0]["latest_job"]["id"] == job["id"]
    assert listed[0]["latest_job"]["focus"] == "テスト"
    assert [s["id"] for s in idea_sessions.list_sessions(1, ItemState.CLOSED, session_factory=session_factory)] == [
        closed
    ]


def test_run_session_rejects_closed_and_active(session_factory):
    session_id = _create(session_factory)
    idea_sessions.run_session(session_id, "", session_factory=session_factory)
    with pytest.raises(IdeaJobAlreadyActive):
        idea_sessions.run_session(session_id, "", session_factory=session_factory)

    idea_sessions.update_session(session_id, state=ItemState.CLOSED, session_factory=session_factory)
    with pytest.raises(RepoItemClosed):
        idea_sessions.run_session(session_id, "", session_factory=session_factory)


def test_list_session_ideas_returns_only_own_proposals(session_factory):
    own = _create(session_factory)
    other = _create(session_factory, "観点B")
    own_job = idea_sessions.run_session(own, "", session_factory=session_factory)["id"]
    finish_idea_job(own_job, IdeaJobStatus.SUCCEEDED, session_factory=session_factory)
    other_job = idea_sessions.run_session(other, "", session_factory=session_factory)["id"]
    with session_factory() as session:
        session.add(IdeaJob(id=99, project_id=1, status=IdeaJobStatus.SUCCEEDED))
        session.commit()
    save_proposals(1, own_job, [_proposal("自分の提案")], session_factory=session_factory)
    save_proposals(1, other_job, [_proposal("別の提案")], session_factory=session_factory)
    save_proposals(1, 99, [_proposal("項目なしの提案")], session_factory=session_factory)

    ideas = idea_sessions.list_session_ideas(own, IdeaStatus.PENDING_STATES, session_factory=session_factory)

    assert [i["title"] for i in ideas] == ["自分の提案"]
