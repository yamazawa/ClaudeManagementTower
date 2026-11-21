import subprocess

import pytest
from sqlalchemy.orm import sessionmaker

from core import deploy_tracking
from core.db import init_db, make_engine
from core.git_client import is_commit_in_head
from core.github_client import GitHubClientError
from core.models import Project, Subtask


@pytest.fixture
def session_factory(tmp_path):
    engine = make_engine(str(tmp_path / "test.db"))
    init_db(bind=engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        session.add_all(
            [
                Project(name="p", github_repo="owner/repo", repo_path="x", default_branch="master"),
                Project(name="q", github_repo="owner/other", repo_path="y", default_branch="master"),
            ]
        )
        session.commit()
    return factory


def _add_subtask(factory, pr_number, state, project_id=1):
    with factory() as session:
        session.add(
            Subtask(
                project_id=project_id,
                github_issue_number=1,
                title="t",
                instruction="",
                branch_name=f"b-{project_id}-{pr_number}",
                github_pr_number=pr_number,
                lifecycle_state=state,
            )
        )
        session.commit()


def _states(factory):
    with factory() as session:
        return {(s.project_id, s.github_pr_number): s.lifecycle_state for s in session.query(Subtask)}


@pytest.fixture
def github(monkeypatch):
    """PR番号→マージコミットの定義と、HEADに含まれるコミットの定義"""
    merged = {}
    in_head = set()
    viewed = []
    monkeypatch.setattr(
        deploy_tracking,
        "list_merged_pull_requests",
        lambda repo: [{"number": n, "mergeCommit": {"oid": c}} for n, c in merged.items()],
    )

    def view(repo, number):
        viewed.append(number)
        return f"old-{number}"

    monkeypatch.setattr(deploy_tracking, "get_pr_merge_commit", view)
    monkeypatch.setattr(deploy_tracking, "is_commit_in_head", lambda path, commit: commit in in_head)
    return merged, in_head, viewed


def test_marks_only_merged_prs_contained_in_head(session_factory, github):
    merged, in_head, _ = github
    merged.update({1: "c1", 2: "c2"})
    in_head.add("c1")
    _add_subtask(session_factory, 1, "merged")
    _add_subtask(session_factory, 2, "merged")
    _add_subtask(session_factory, 3, "resolved")

    updated = deploy_tracking.mark_deployed(1, "repo", session_factory)

    assert len(updated) == 1
    assert _states(session_factory) == {(1, 1): "deployed", (1, 2): "merged", (1, 3): "resolved"}


def test_fetches_merge_commit_of_pr_missing_in_list(session_factory, github):
    _, in_head, viewed = github
    in_head.add("old-5")
    _add_subtask(session_factory, 5, "merged")

    deploy_tracking.mark_deployed(1, "repo", session_factory)

    assert viewed == [5]
    assert _states(session_factory) == {(1, 5): "deployed"}


def test_failed_fetch_of_one_pr_does_not_stop_others(session_factory, github, monkeypatch):
    merged, in_head, _ = github
    merged[1] = "c1"
    in_head.add("c1")

    def fail(repo, number):
        raise GitHubClientError("not found")

    monkeypatch.setattr(deploy_tracking, "get_pr_merge_commit", fail)
    _add_subtask(session_factory, 1, "merged")
    _add_subtask(session_factory, 9, "merged")

    deploy_tracking.mark_deployed(1, "repo", session_factory)

    assert _states(session_factory) == {(1, 1): "deployed", (1, 9): "merged"}


def test_skips_github_when_no_merged_subtask(session_factory, monkeypatch):
    def fail(repo):
        raise AssertionError("should not call GitHub")

    monkeypatch.setattr(deploy_tracking, "list_merged_pull_requests", fail)
    _add_subtask(session_factory, 1, "resolved")

    assert deploy_tracking.mark_deployed(1, "repo", session_factory) == []


def test_mark_all_merged_without_checking_head(session_factory, monkeypatch):
    monkeypatch.setattr(deploy_tracking, "list_merged_pull_requests", lambda repo: pytest.fail("not called"))
    _add_subtask(session_factory, 1, "merged")
    _add_subtask(session_factory, 2, "resolved")
    _add_subtask(session_factory, 3, "merged", project_id=2)

    updated = deploy_tracking.mark_all_merged_deployed(1, session_factory)

    assert len(updated) == 1
    assert _states(session_factory) == {(1, 1): "deployed", (1, 2): "resolved", (2, 3): "merged"}


def test_mark_for_repo_targets_only_same_repo(session_factory, github):
    merged, in_head, _ = github
    merged[1] = "c1"
    in_head.add("c1")
    _add_subtask(session_factory, 1, "merged", project_id=1)
    _add_subtask(session_factory, 1, "merged", project_id=2)

    deploy_tracking.mark_deployed_for_repo("owner/repo", "repo", session_factory)

    assert _states(session_factory) == {(1, 1): "deployed", (2, 1): "merged"}


def _git(repo, *args) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()


def test_is_commit_in_head(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "--allow-empty", "-m", "a")
    first = _git(tmp_path, "rev-parse", "HEAD")
    _git(tmp_path, "checkout", "-q", "-b", "other")
    _git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "--allow-empty", "-m", "b")
    other = _git(tmp_path, "rev-parse", "HEAD")
    _git(tmp_path, "checkout", "-q", first)

    assert is_commit_in_head(str(tmp_path), first)
    assert not is_commit_in_head(str(tmp_path), other)
    assert not is_commit_in_head(str(tmp_path), "0" * 40)
