import pytest
from sqlalchemy.orm import sessionmaker

from core import pr_sync
from core.db import init_db, make_engine
from core.models import Project, Subtask


@pytest.fixture
def session_factory(tmp_path):
    engine = make_engine(str(tmp_path / "test.db"))
    init_db(bind=engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        session.add(
            Project(name="p", github_repo="owner/repo", repo_path="x", default_branch="master")
        )
        session.commit()
    return factory


def _add_subtask(factory, pr_number, state, branch):
    with factory() as session:
        session.add(
            Subtask(
                project_id=1,
                github_issue_number=1,
                title="t",
                instruction="",
                branch_name=branch,
                github_pr_number=pr_number,
                lifecycle_state=state,
            )
        )
        session.commit()


def _states(factory):
    with factory() as session:
        return {s.github_pr_number: s.lifecycle_state for s in session.query(Subtask)}


@pytest.mark.parametrize(
    ("pr", "expected"),
    [
        ({"mergedAt": "2026-01-01T00:00:00Z", "state": "MERGED", "isDraft": False}, "merged"),
        ({"mergedAt": None, "state": "CLOSED", "isDraft": False}, "closed"),
        ({"mergedAt": None, "state": "OPEN", "isDraft": True}, "draft"),
        ({"mergedAt": None, "state": "OPEN", "isDraft": False}, "in_review"),
    ],
)
def test_lifecycle_state_from_pr(pr, expected):
    assert pr_sync.lifecycle_state_from_pr(pr) == expected


def test_sync_updates_changed_states(session_factory, monkeypatch):
    _add_subtask(session_factory, 10, "draft", "b10")
    _add_subtask(session_factory, 11, "in_review", "b11")
    _add_subtask(session_factory, 12, "in_review", "b12")
    monkeypatch.setattr(
        pr_sync,
        "list_pull_request_states",
        lambda repo: [
            {"number": 10, "isDraft": False, "state": "OPEN", "mergedAt": None},
            {"number": 11, "isDraft": False, "state": "MERGED", "mergedAt": "x"},
        ],
    )

    updated = pr_sync.sync_all_projects(session_factory)

    assert updated == [
        {"subtask_id": 1, "lifecycle_state": "in_review"},
        {"subtask_id": 2, "lifecycle_state": "merged"},
    ]
    assert _states(session_factory) == {10: "in_review", 11: "merged", 12: "in_review"}


def test_sync_skips_github_when_no_targets(session_factory, monkeypatch):
    _add_subtask(session_factory, 10, "merged", "b10")

    def fail(repo):
        raise AssertionError("should not call GitHub")

    monkeypatch.setattr(pr_sync, "list_pull_request_states", fail)

    assert pr_sync.sync_all_projects(session_factory) == []


def test_mark_prs_merged(session_factory):
    _add_subtask(session_factory, 10, "in_review", "b10")
    _add_subtask(session_factory, 11, "in_review", "b11")

    pr_sync.mark_prs_merged("owner/repo", [10], session_factory)

    assert _states(session_factory) == {10: "merged", 11: "in_review"}


def test_mark_prs_merged_ignores_other_repo(session_factory):
    _add_subtask(session_factory, 10, "in_review", "b10")

    pr_sync.mark_prs_merged("other/repo", [10], session_factory)

    assert _states(session_factory) == {10: "in_review"}
