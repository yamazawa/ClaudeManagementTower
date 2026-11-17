import subprocess
from pathlib import Path

import pytest

from core.git_client import (
    commit_merge,
    is_merge_in_progress,
    list_unmerged_files,
    merge_remote_branch,
    prepare_detached_worktree,
    push_head_to,
)


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", check=True
    )
    return result.stdout


def _commit_file(cwd: Path, name: str, content: str, message: str) -> None:
    (cwd / name).write_text(content, encoding="utf-8")
    _git(cwd, "add", name)
    _git(cwd, "commit", "-m", message)


@pytest.fixture
def repo(tmp_path):
    """masterとfeatureを持つoriginと、そのclone(本体)を作る"""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", "-b", "master", str(origin))
    main = tmp_path / "main"
    _git(tmp_path, "clone", str(origin), str(main))
    _git(main, "config", "user.name", "test")
    _git(main, "config", "user.email", "test@example.com")
    _commit_file(main, "a.txt", "base\n", "base")
    _git(main, "push", "origin", "HEAD:master")
    _git(main, "checkout", "-b", "feature")
    _commit_file(main, "a.txt", "feature\n", "feature")
    _git(main, "push", "origin", "feature")
    _git(main, "checkout", "master")
    return main


def _advance_master(main: Path, name: str, content: str) -> None:
    _commit_file(main, name, content, "master")
    _git(main, "push", "origin", "master")


def test_merge_without_conflict_is_pushed(repo, tmp_path):
    _advance_master(repo, "b.txt", "other\n")
    worktree = tmp_path / "wt"

    prepare_detached_worktree(str(repo), str(worktree), "feature")
    assert merge_remote_branch(str(worktree), "master", "merge") is True
    push_head_to(str(worktree), "feature")

    _git(repo, "fetch", "origin")
    _git(repo, "merge-base", "--is-ancestor", "origin/master", "origin/feature")


def test_conflict_is_left_in_progress(repo, tmp_path):
    _advance_master(repo, "a.txt", "master\n")
    worktree = tmp_path / "wt"

    prepare_detached_worktree(str(repo), str(worktree), "feature")

    assert merge_remote_branch(str(worktree), "master", "merge") is False
    assert list_unmerged_files(str(worktree)) == ["a.txt"]
    assert is_merge_in_progress(str(worktree)) is True

    (worktree / "a.txt").write_text("resolved\n", encoding="utf-8")
    _git(worktree, "add", "a.txt")
    commit_merge(str(worktree))
    assert is_merge_in_progress(str(worktree)) is False


def test_existing_worktree_is_reset_to_remote(repo, tmp_path):
    _advance_master(repo, "a.txt", "master\n")
    worktree = tmp_path / "wt"
    prepare_detached_worktree(str(repo), str(worktree), "feature")
    merge_remote_branch(str(worktree), "master", "merge")

    prepare_detached_worktree(str(repo), str(worktree), "feature")

    assert is_merge_in_progress(str(worktree)) is False
    assert (worktree / "a.txt").read_text(encoding="utf-8") == "feature\n"
