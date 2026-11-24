import subprocess
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

from core import repo_initial_setup, repo_setup
from core.config import settings
from core.db import init_db, make_engine
from core.github_client import GitHubClientError
from core.lifecycle import LifecycleState
from core.models import Project, Subtask
from core.repo_setup import (
    NewRepo,
    RepoSetupError,
    RepoValidationError,
    create_repository,
    normalize_new_repo,
)


def _git(cwd, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", check=True
    )
    return result.stdout


@pytest.fixture
def factory(tmp_path, monkeypatch):
    engine = make_engine(str(tmp_path / "test.db"))
    init_db(bind=engine)
    monkeypatch.setattr(settings, "new_repo_base_dir", str(tmp_path / "git"))
    monkeypatch.setattr(settings, "worktree_base_dir", str(tmp_path / "worktrees"))
    monkeypatch.setattr(settings, "new_repo_owner", "owner")
    for key in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{key}_NAME", "test")
        monkeypatch.setenv(f"GIT_{key}_EMAIL", "test@example.com")
    return sessionmaker(bind=engine)


class FakeGitHub:
    """ghの代わりに、ローカルのbareリポジトリをGitHubとして扱う"""

    def __init__(self, tmp_path, monkeypatch):
        self.origin = tmp_path / "origin.git"
        self.calls = []
        self.fail_on = None
        monkeypatch.setattr(repo_setup, "create_repo_from_local", self.create_repo)
        for name in ("create_issue", "create_draft_pr", "mark_pr_ready", "merge_pull_request", "close_issue"):
            monkeypatch.setattr(repo_initial_setup, name, getattr(self, name))
        monkeypatch.setattr(repo_initial_setup, "mark_deployed", lambda *args: [])

    def _record(self, name, *args):
        self.calls.append((name, *args))
        if name == self.fail_on:
            raise GitHubClientError(f"{name} failed")

    def create_repo(self, repo, source, description, visibility):
        self._record("create_repo", repo, description, visibility)
        _git(source, "init", "--bare", "-b", "master", str(self.origin))
        _git(source, "remote", "add", "origin", str(self.origin))
        _git(source, "push", "-u", "origin", "master")

    def create_issue(self, repo, title, body):
        self._record("create_issue", repo, title)
        return {"number": 1, "url": "u"}

    def create_draft_pr(self, repo, base, head, title, body):
        self._record("create_draft_pr", repo, head, title, body)
        self.head = head
        return {"number": 2, "url": "u"}

    def mark_pr_ready(self, repo, number):
        self._record("mark_pr_ready", repo, number)

    def merge_pull_request(self, repo, number):
        self._record("merge_pull_request", repo, number)
        _git(self.origin, "update-ref", "refs/heads/master", f"refs/heads/{self.head}")

    def close_issue(self, repo, number):
        self._record("close_issue", repo, number)


@pytest.fixture
def github(tmp_path, monkeypatch):
    return FakeGitHub(tmp_path, monkeypatch)


NEW_REPO = NewRepo("NewTool", "新ツール", "何かをするツール")


def test_normalize_new_repo_strips_values():
    assert normalize_new_repo(" a-b.c_1 ", " 名前 ", " 説明 ") == NewRepo("a-b.c_1", "名前", "説明")


@pytest.mark.parametrize(
    "values",
    [("", "名", "説明"), ("-a", "名", "説明"), ("日本語", "名", "説明"), ("a b", "名", "説明"),
     ("a", " ", "説明"), ("a", "名", " ")],
)
def test_normalize_new_repo_rejects_invalid_input(values):
    with pytest.raises(RepoValidationError):
        normalize_new_repo(*values)


def test_new_repo_owner_defaults_to_self_repo_owner(monkeypatch):
    monkeypatch.setattr(settings, "new_repo_owner", "")
    monkeypatch.setattr(settings, "self_repo", "me/Tower")

    assert NEW_REPO.github_repo == "me/NewTool"


def test_create_repository_completes_setup_issue_and_mr(factory, github):
    result = create_repository(NEW_REPO, factory)

    assert result == {"project_id": 1, "issue_number": 1, "pr_number": 2, "warnings": []}
    assert [c[0] for c in github.calls] == [
        "create_repo", "create_issue", "create_draft_pr", "mark_pr_ready", "merge_pull_request", "close_issue",
    ]
    assert github.calls[0] == ("create_repo", "owner/NewTool", "何かをするツール", "private")


def test_create_repository_registers_project_and_merged_mr(factory, github):
    create_repository(NEW_REPO, factory)

    with factory() as session:
        project = session.query(Project).one()
        subtask = session.query(Subtask).one()
        assert (project.name, project.github_repo, project.display_name, project.description) == (
            "NewTool", "owner/NewTool", "新ツール", "何かをするツール",
        )
        assert (subtask.github_issue_number, subtask.github_pr_number, subtask.lifecycle_state) == (
            1, 2, LifecycleState.MERGED,
        )


def test_create_repository_pulls_setup_files_into_local_repo(factory, github):
    create_repository(NEW_REPO, factory)

    repo_path = NEW_REPO.repo_path
    assert _git(repo_path, "ls-files").split() == [".gitignore", "CLAUDE.md", "README.md"]
    assert _git(repo_path, "branch", "--list").split() == ["*", "master"]
    assert _git(repo_path, "worktree", "list").count("\n") == 1


def test_claude_md_contains_names_and_description(factory, github):
    create_repository(NEW_REPO, factory)

    with open(f"{NEW_REPO.repo_path}/CLAUDE.md", encoding="utf-8") as f:
        content = f.read()
    assert content.startswith("# 新ツール プロジェクト指示\n\n何かをするツール\n")


def test_create_repository_rejects_existing_folder(factory, github):
    Path(NEW_REPO.repo_path).mkdir(parents=True)

    with pytest.raises(RepoValidationError):
        create_repository(NEW_REPO, factory)
    assert github.calls == []


def test_create_repository_rejects_registered_repo(factory, github):
    with factory() as session:
        session.add(Project(name="x", github_repo="owner/NewTool", repo_path="x", default_branch="master"))
        session.commit()

    with pytest.raises(RepoValidationError):
        create_repository(NEW_REPO, factory)


def test_create_repository_does_not_register_when_github_creation_fails(factory, github):
    github.fail_on = "create_repo"

    with pytest.raises(RepoSetupError) as exc_info:
        create_repository(NEW_REPO, factory)

    assert exc_info.value.project_id is None
    with factory() as session:
        assert session.query(Project).count() == 0


def test_create_repository_keeps_registration_when_setup_fails(factory, github):
    github.fail_on = "merge_pull_request"

    with pytest.raises(RepoSetupError) as exc_info:
        create_repository(NEW_REPO, factory)

    assert exc_info.value.project_id == 1
    assert "初期設定" in str(exc_info.value)
    with factory() as session:
        assert session.query(Subtask).one().lifecycle_state == LifecycleState.DRAFT
