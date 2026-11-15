import re
import subprocess
from pathlib import Path

from filelock import FileLock, Timeout

GIT_TIMEOUT_SECONDS = 60
WORKTREE_LOCK_TIMEOUT_SECONDS = 60


class GitClientError(RuntimeError):
    pass


def _run_git(args: list[str], cwd: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitClientError(f"git {' '.join(args)} がタイムアウトしました") from exc
    if result.returncode != 0:
        raise GitClientError(result.stderr.strip())
    return result.stdout


def slugify(text: str) -> str:
    ascii_text = text.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text).strip("-").lower()


def create_worktree(
    repo_path: str,
    branch_name: str,
    base_branch: str,
    worktree_path: str,
) -> None:
    # worktree作成はリポジトリ共有のGitメタデータを変更するため、
    # 同一リポジトリへの同時作成をリポジトリ単位で排他する
    lock_path = Path(repo_path) / ".git" / "claude-tower-worktree.lock"
    try:
        with FileLock(str(lock_path), timeout=WORKTREE_LOCK_TIMEOUT_SECONDS):
            _run_git(["fetch", "origin", base_branch], cwd=repo_path)
            _run_git(
                ["worktree", "add", "-b", branch_name, worktree_path, f"origin/{base_branch}"],
                cwd=repo_path,
            )
    except Timeout as exc:
        raise GitClientError("worktree作成の排他ロック取得がタイムアウトしました") from exc


def commit_subtask_instruction(worktree_path: str, title: str, instruction: str) -> None:
    subtask_dir = Path(worktree_path) / ".claude-tower"
    subtask_dir.mkdir(parents=True, exist_ok=True)
    (subtask_dir / "subtask.md").write_text(
        f"# サブタスク: {title}\n\n{instruction}\n",
        encoding="utf-8",
    )
    _run_git(["add", ".claude-tower/subtask.md"], cwd=worktree_path)
    _run_git(["commit", "-m", f"[サブタスク] {title} ― 指示を記録"], cwd=worktree_path)


def push_branch(worktree_path: str, branch_name: str) -> None:
    _run_git(["push", "-u", "origin", branch_name], cwd=worktree_path)
