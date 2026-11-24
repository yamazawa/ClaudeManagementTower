import subprocess

import pytest

from core.git_client import GitClientError, commit_files, init_local_repo


def _git(cwd, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", check=True
    )
    return result.stdout


def test_init_local_repo_creates_repo_with_given_branch(tmp_path):
    path = tmp_path / "new"

    init_local_repo(str(path), "master")

    assert _git(path, "symbolic-ref", "--short", "HEAD").strip() == "master"


def test_init_local_repo_refuses_existing_folder(tmp_path):
    with pytest.raises(FileExistsError):
        init_local_repo(str(tmp_path), "master")


def test_commit_files_commits_only_given_paths(tmp_path):
    init_local_repo(str(tmp_path / "r"), "master")
    repo = tmp_path / "r"
    _git(repo, "config", "user.name", "test")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "a.txt").write_text("a", encoding="utf-8")
    (repo / "b.txt").write_text("b", encoding="utf-8")

    commit_files(str(repo), ["a.txt"], "msg")

    assert _git(repo, "show", "--name-only", "--format=%s", "HEAD").split() == ["msg", "a.txt"]


def test_commit_files_raises_when_nothing_to_commit(tmp_path):
    init_local_repo(str(tmp_path / "r"), "master")

    with pytest.raises(GitClientError):
        commit_files(str(tmp_path / "r"), [], "msg")
