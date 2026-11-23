"""サブタスク作成の途中失敗時の後始末

作成済みの段階だけを、強制なしの操作で取り消す。
"""

import logging
from collections.abc import Callable
from enum import Enum

from core.git_client import (
    GitClientError,
    delete_local_branch,
    delete_remote_branch,
    discard_subtask_instruction,
    remove_worktree,
)

logger = logging.getLogger(__name__)


class SubtaskCreationStage(str, Enum):
    """サブタスク作成で完了した段階"""

    WORKTREE_CREATED = "worktree_created"
    INSTRUCTION_COMMITTED = "instruction_committed"
    BRANCH_PUSHED = "branch_pushed"


def rollback_subtask_creation(
    repo_path: str,
    worktree_path: str,
    branch_name: str,
    completed: set[SubtaskCreationStage],
) -> list[str]:
    """完了した段階を取り消し、取り消せずに残ったものを返す

    git branch -dは上流ブランチで取り込み済みかを判定するため、リモートブランチより先にローカルブランチを削除する。
    worktreeを削除できない場合、チェックアウト中のローカルブランチも削除できない。
    """
    if SubtaskCreationStage.WORKTREE_CREATED not in completed:
        return []
    steps = _rollback_steps(repo_path, worktree_path, branch_name, completed)
    return [leftover for leftover, undo in steps if not _try_undo(leftover, undo)]


def _rollback_steps(
    repo_path: str,
    worktree_path: str,
    branch_name: str,
    completed: set[SubtaskCreationStage],
) -> list[tuple[str, Callable[[], None]]]:
    def remove_worktree_step() -> None:
        if SubtaskCreationStage.INSTRUCTION_COMMITTED not in completed:
            discard_subtask_instruction(worktree_path)
        remove_worktree(repo_path, worktree_path)

    steps = [
        (f"worktree {worktree_path}", remove_worktree_step),
        (f"ローカルブランチ {branch_name}", lambda: delete_local_branch(repo_path, branch_name)),
    ]
    if SubtaskCreationStage.BRANCH_PUSHED in completed:
        steps.append(
            (f"リモートブランチ origin/{branch_name}", lambda: delete_remote_branch(repo_path, branch_name))
        )
    return steps


def _try_undo(leftover: str, undo: Callable[[], None]) -> bool:
    try:
        undo()
    except (GitClientError, OSError) as exc:
        logger.warning("サブタスク作成の後始末に失敗しました（%s）: %s", leftover, exc)
        return False
    return True


def describe_rollback_result(leftovers: list[str]) -> str:
    """後始末の結果をエラーメッセージに添える文言"""
    if not leftovers:
        return "作成済みのworktree・ブランチは削除しました。"
    return "後始末できずに残ったもの: " + "、".join(leftovers)
