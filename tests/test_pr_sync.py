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
        ({"mergedAt": None, "state": "CLOSED", "isDraft": False}, "canceled"),
        ({"mergedAt": None, "state": "OPEN", "isDraft": True}, "draft"),
        ({"mergedAt": None, "state": "OPEN", "isDraft": False}, "resolved"),
    ],
)
def test_lifecycle_state_from_pr(pr, expected):
    assert pr_sync.lifecycle_state_from_pr(pr) == expected


def test_sync_updates_changed_states(session_factory, monkeypatch):
    _add_subtask(session_factory, 10, "draft", "b10")
    _add_subtask(session_factory, 11, "resolved", "b11")
    _add_subtask(session_factory, 12, "resolved", "b12")
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
        {"subtask_id": 1, "lifecycle_state": "resolved"},
        {"subtask_id": 2, "lifecycle_state": "merged"},
    ]
    assert _states(session_factory) == {10: "resolved", 11: "merged", 12: "resolved"}


def _pr(number, branch, closing=(), repo="owner/repo", **state):
    owner, name = repo.split("/")
    refs = [{"number": n, "repository": {"name": name, "owner": {"login": owner}}} for n in closing]
    pr = {"number": number, "isDraft": False, "state": "OPEN", "mergedAt": None}
    return {**pr, "title": f"PR{number}", "headRefName": branch, "closingIssuesReferences": refs, **state}


@pytest.mark.parametrize(
    ("pr", "expected"),
    [
        (_pr(1, "issue-5-fix", closing=[7]), 7),
        (_pr(1, "issue-5-fix", closing=[7], repo="other/repo"), 5),
        (_pr(1, "issue-5-fix"), 5),
        (_pr(1, "feature-x"), None),
        (_pr(1, "issue-x-fix"), None),
    ],
)
def test_linked_issue_number(pr, expected):
    assert pr_sync.linked_issue_number(pr, "Owner/Repo") == expected


def test_sync_imports_untracked_prs(session_factory, monkeypatch):
    _add_subtask(session_factory, 10, "merged", "b10")
    _add_subtask(session_factory, None, "draft", "issue-1-pending")
    monkeypatch.setattr(
        pr_sync,
        "list_pull_request_states",
        lambda repo: [
            _pr(10, "b10"),
            _pr(11, "issue-1-pending"),
            _pr(12, "issue-3-manual", isDraft=True),
            _pr(13, "manual", closing=[4], state="MERGED", mergedAt="x"),
            _pr(14, "unlinked"),
        ],
    )

    updated = pr_sync.sync_all_projects(session_factory)

    assert updated == [
        {"subtask_id": 3, "lifecycle_state": "draft"},
        {"subtask_id": 4, "lifecycle_state": "merged"},
    ]
    with session_factory() as session:
        imported = {
            s.github_pr_number: (s.github_issue_number, s.title, s.branch_name)
            for s in session.query(Subtask).filter(Subtask.id > 2)
        }
    assert imported == {12: (3, "PR12", "issue-3-manual"), 13: (4, "PR13", "manual")}


def test_sync_does_not_import_twice(session_factory, monkeypatch):
    monkeypatch.setattr(
        pr_sync, "list_pull_request_states", lambda repo: [_pr(12, "issue-3-manual")]
    )

    pr_sync.sync_all_projects(session_factory)

    assert pr_sync.sync_all_projects(session_factory) == []
    assert _states(session_factory) == {12: "resolved"}


def test_sync_continues_when_one_repo_fails(session_factory, monkeypatch):
    with session_factory() as session:
        session.add(
            Project(name="q", github_repo="owner/broken", repo_path="y", default_branch="master")
        )
        session.commit()
    _add_subtask(session_factory, 10, "draft", "b10")

    def list_states(repo):
        if repo == "owner/broken":
            raise RuntimeError("gh failed")
        return [_pr(10, "b10")]

    monkeypatch.setattr(pr_sync, "list_pull_request_states", list_states)

    updated = pr_sync.sync_all_projects(session_factory)

    assert updated == [{"subtask_id": 1, "lifecycle_state": "resolved"}]
    assert _states(session_factory) == {10: "resolved"}


def test_sync_fetches_shared_repo_once(session_factory, monkeypatch):
    with session_factory() as session:
        session.add(
            Project(name="q", github_repo="owner/repo", repo_path="y", default_branch="master")
        )
        session.commit()
    calls = []
    monkeypatch.setattr(
        pr_sync, "list_pull_request_states", lambda repo: calls.append(repo) or []
    )

    pr_sync.sync_all_projects(session_factory)

    assert calls == ["owner/repo"]


def test_mark_prs_merged(session_factory):
    _add_subtask(session_factory, 10, "resolved", "b10")
    _add_subtask(session_factory, 11, "resolved", "b11")

    pr_sync.mark_prs_merged("owner/repo", [10], session_factory)

    assert _states(session_factory) == {10: "merged", 11: "resolved"}


def test_mark_prs_merged_ignores_other_repo(session_factory):
    _add_subtask(session_factory, 10, "resolved", "b10")

    pr_sync.mark_prs_merged("other/repo", [10], session_factory)

    assert _states(session_factory) == {10: "resolved"}
