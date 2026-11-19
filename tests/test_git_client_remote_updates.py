import subprocess
from pathlib import Path

import pytest

from core.git_client import has_remote_updates


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", check=True
    )
    return result.stdout


def _clone(origin: Path, path: Path) -> Path:
    _git(origin.parent, "clone", str(origin), str(path))
    _git(path, "config", "user.name", "test")
    _git(path, "config", "user.email", "test@example.com")
    return path


def _commit_and_push(cwd: Path, content: str) -> None:
    (cwd / "a.txt").write_text(content, encoding="utf-8")
    _git(cwd, "add", "a.txt")
    _git(cwd, "commit", "-m", content)
    _git(cwd, "push", "origin", "HEAD:master")


@pytest.fixture
def repos(tmp_path):
    """デプロイ先のcloneと、originへ変更をpushする別のcloneを作る"""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", "-b", "master", str(origin))
    other = _clone(origin, tmp_path / "other")
    _commit_and_push(other, "base")
    deployed = _clone(origin, tmp_path / "deployed")
    return deployed, other


def test_no_updates_when_up_to_date(repos):
    deployed, _ = repos
    assert has_remote_updates(str(deployed), "master") is False


def test_updates_detected_after_remote_push(repos):
    deployed, other = repos
    _commit_and_push(other, "next")
    assert has_remote_updates(str(deployed), "master") is True

    _git(deployed, "pull", "origin", "master")
    assert has_remote_updates(str(deployed), "master") is False


def test_local_only_commits_are_not_updates(repos):
    deployed, _ = repos
    (deployed / "b.txt").write_text("local", encoding="utf-8")
    _git(deployed, "add", "b.txt")
    _git(deployed, "commit", "-m", "local")
    assert has_remote_updates(str(deployed), "master") is False
