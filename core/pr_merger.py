"""PRのマージ（競合時はベースを取り込み、Claudeで競合解決してからマージ）

競合したPRは、ベースブランチをPRブランチへマージして最新化する。
履歴を書き換えずforce pushも不要なため、rebaseではなくmergeで取り込む。
"""

import asyncio
import time
from pathlib import Path

from core.claude_client import run_claude
from core.claude_prompts import CONFLICT_RESOLUTION_POLICY_PROMPT
from core.git_client import (
    commit_merge,
    is_merge_in_progress,
    list_unmerged_files,
    merge_remote_branch,
    prepare_detached_worktree,
    push_head_to,
)
from core.github_client import get_pr_mergeable, merge_pull_request

MERGEABLE = "MERGEABLE"
CONFLICTING = "CONFLICTING"
UNKNOWN = "UNKNOWN"

MERGEABLE_POLL_INTERVAL_SECONDS = 2
MERGEABLE_POLL_TIMEOUT_SECONDS = 60
MERGE_WORKTREE_PREFIX = "merge-pr-"
CONFLICT_MARKERS = ("<<<<<<< ", ">>>>>>> ")


class PrMergeError(RuntimeError):
    pass


def wait_for_mergeable_state(repo: str, number: int, stale_state: str | None = None) -> str:
    """GitHubがmergeableを判定し終える(UNKNOWN以外になる)まで待つ

    push直後はmergeableの再計算が始まるまでに間があり、UNKNOWNを経由せず
    push前の値(stale_state)を返し続けることがあるため、その値も
    再計算中とみなして待つ。
    """
    deadline = time.monotonic() + MERGEABLE_POLL_TIMEOUT_SECONDS
    state = get_pr_mergeable(repo, number)
    while state in (UNKNOWN, stale_state) and time.monotonic() < deadline:
        time.sleep(MERGEABLE_POLL_INTERVAL_SECONDS)
        state = get_pr_mergeable(repo, number)
    return state


def merge_pr_with_update(repo: str, repo_path: str, worktree_base_dir: str, pr: dict) -> None:
    """PRをマージする

    競合している場合は、ベースブランチを取り込んで競合解決してからマージする。
    """
    number = pr["number"]
    state = wait_for_mergeable_state(repo, number)
    if state == CONFLICTING:
        worktree_path = str(Path(worktree_base_dir) / f"{MERGE_WORKTREE_PREFIX}{number}")
        update_pr_branch(repo_path, worktree_path, pr)
        state = wait_for_mergeable_state(repo, number, stale_state=CONFLICTING)
    if state != MERGEABLE:
        raise PrMergeError(f"PR #{number} がマージ可能になりません（{state}）")
    merge_pull_request(repo, number)


def update_pr_branch(repo_path: str, worktree_path: str, pr: dict) -> None:
    """PRブランチにベースブランチを取り込み、競合を解決してpushする"""
    head, base = pr["headRefName"], pr["baseRefName"]
    prepare_detached_worktree(repo_path, worktree_path, head)
    message = f"[マージして最新化] PR #{pr['number']} に{base}を取り込み"
    if not merge_remote_branch(worktree_path, base, message):
        resolve_conflicts_with_claude(worktree_path, pr)
    push_head_to(worktree_path, head)


def resolve_conflicts_with_claude(worktree_path: str, pr: dict) -> None:
    conflicted = list_unmerged_files(worktree_path)
    asyncio.run(
        run_claude(
            build_conflict_prompt(pr, conflicted),
            worktree_path,
            policy_prompt=CONFLICT_RESOLUTION_POLICY_PROMPT,
        )
    )
    remaining = list_unmerged_files(worktree_path) or files_with_conflict_markers(worktree_path, conflicted)
    if remaining:
        raise PrMergeError(f"PR #{pr['number']} の競合が解消されていません: {', '.join(remaining)}")
    if is_merge_in_progress(worktree_path):
        commit_merge(worktree_path)


def files_with_conflict_markers(worktree_path: str, paths: list[str]) -> list[str]:
    def has_marker(path: str) -> bool:
        file = Path(worktree_path) / path
        if not file.is_file():
            return False
        lines = file.read_text(encoding="utf-8", errors="ignore").splitlines()
        return any(line.startswith(CONFLICT_MARKERS) for line in lines)

    return [path for path in paths if has_marker(path)]


def build_conflict_prompt(pr: dict, conflicted: list[str]) -> str:
    files = "\n".join(f"- {path}" for path in conflicted)
    return (
        f"PR #{pr['number']}（{pr['headRefName']}）に{pr['baseRefName']}を"
        f"マージしたところ、以下のファイルで競合しました。\n"
        f"{files}\n"
        "競合を解消し、git addまで行ってください。"
    )
