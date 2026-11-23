import subprocess
import sys
from pathlib import Path

import pytest

from core.git_client import (
    commit_subtask_instruction,
    create_worktree,
    push_branch,
    unlink_shared_venv,
)
from core.subtask_rollback import (
    SubtaskCreationStage,
    describe_rollback_result,
    rollback_subtask_creation,
)

BRANCH = "issue-1-x-1"
ALL_STAGES = set(SubtaskCreationStage)


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", check=True
    )
    return result.stdout


@pytest.fixture
def repo(tmp_path):
    """masterを持つoriginと、そのclone(本体)を作る"""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", "-b", "master", str(origin))
    main = tmp_path / "main"
    _git(tmp_path, "clone", str(origin), str(main))
    _git(main, "config", "user.name", "test")
    _git(main, "config", "user.email", "test@example.com")
    (main / "a.txt").write_text("base\n", encoding="utf-8")
    _git(main, "add", "a.txt")
    _git(main, "commit", "-m", "base")
    _git(main, "push", "origin", "HEAD:master")
    return main


def _create(repo: Path, worktree: Path, stages: set[SubtaskCreationStage]) -> None:
    """指定した段階までサブタスク作成を進める"""
    create_worktree(str(repo), BRANCH, "master", str(worktree))
    if SubtaskCreationStage.INSTRUCTION_COMMITTED in stages:
        commit_subtask_instruction(str(worktree), "t", "")
    else:
        # コミット前に失敗した状態（指示ファイルを追加済み）を再現する
        (worktree / ".claude-tower").mkdir()
        (worktree / ".claude-tower" / "subtask.md").write_text("x", encoding="utf-8")
        _git(worktree, "add", ".claude-tower/subtask.md")
    if SubtaskCreationStage.BRANCH_PUSHED in stages:
        push_branch(str(worktree), BRANCH)


def _local_branches(repo: Path) -> str:
    return _git(repo, "branch", "--list", BRANCH)


def _remote_branches(repo: Path) -> str:
    return _git(repo, "ls-remote", "--heads", "origin", BRANCH)


@pytest.mark.parametrize("stages", [{SubtaskCreationStage.WORKTREE_CREATED}, ALL_STAGES])
def test_rollback_removes_created_items(repo, tmp_path, stages):
    worktree = tmp_path / "wt"
    _create(repo, worktree, stages)

    leftovers = rollback_subtask_creation(str(repo), str(worktree), BRANCH, stages)

    assert leftovers == []
    assert not worktree.exists()
    assert _local_branches(repo) == ""
    assert _remote_branches(repo) == ""


@pytest.mark.skipif(sys.platform != "win32", reason="ジャンクションはWindowsのみ")
def test_rollback_keeps_shared_venv(repo, tmp_path):
    """worktree削除で、ジャンクション先の本体の仮想環境を巻き込まない"""
    (repo / ".venv").mkdir()
    (repo / ".venv" / "keep.txt").write_text("x", encoding="utf-8")
    worktree = tmp_path / "wt"
    _create(repo, worktree, ALL_STAGES)
    assert (worktree / ".venv" / "keep.txt").exists()

    rollback_subtask_creation(str(repo), str(worktree), BRANCH, ALL_STAGES)

    assert not worktree.exists()
    assert (repo / ".venv" / "keep.txt").exists()


def test_rollback_keeps_unpushed_commit_branch(repo, tmp_path):
    """push前に失敗した場合、未pushのコミットを持つブランチは強制削除せず残す"""
    worktree = tmp_path / "wt"
    stages = {SubtaskCreationStage.WORKTREE_CREATED, SubtaskCreationStage.INSTRUCTION_COMMITTED}
    _create(repo, worktree, stages)

    leftovers = rollback_subtask_creation(str(repo), str(worktree), BRANCH, stages)

    assert leftovers == [f"ローカルブランチ {BRANCH}"]
    assert BRANCH in _local_branches(repo)


def test_rollback_reports_worktree_with_user_changes(repo, tmp_path):
    """worktreeに想定外の変更がある場合、強制削除せず残したものを返す"""
    worktree = tmp_path / "wt"
    _create(repo, worktree, ALL_STAGES)
    (worktree / "a.txt").write_text("changed\n", encoding="utf-8")

    leftovers = rollback_subtask_creation(str(repo), str(worktree), BRANCH, ALL_STAGES)

    assert leftovers == [f"worktree {worktree}", f"ローカルブランチ {BRANCH}"]
    assert worktree.exists()
    assert _remote_branches(repo) == ""


def test_rollback_without_worktree_does_nothing(repo, tmp_path):
    assert rollback_subtask_creation(str(repo), str(tmp_path / "wt"), BRANCH, set()) == []


def test_describe_rollback_result():
    assert "削除しました" in describe_rollback_result([])
    assert describe_rollback_result(["a", "b"]).endswith("a、b")


@pytest.mark.skipif(sys.platform != "win32", reason="ジャンクションはWindowsのみ")
def test_unlink_shared_venv_keeps_link_target(tmp_path):
    target = tmp_path / "venv"
    target.mkdir()
    (target / "keep.txt").write_text("x", encoding="utf-8")
    worktree = tmp_path / "wt"
    worktree.mkdir()
    subprocess.run(["cmd", "/c", "mklink", "/J", str(worktree / ".venv"), str(target)], check=True, capture_output=True)

    unlink_shared_venv(str(worktree))

    assert not (worktree / ".venv").exists()
    assert (target / "keep.txt").exists()
