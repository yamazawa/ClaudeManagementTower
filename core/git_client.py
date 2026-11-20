import re
import subprocess
from datetime import datetime, timezone
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

    link_shared_venv(repo_path, worktree_path)


def link_shared_venv(repo_path: str, worktree_path: str) -> None:
    """本体リポジトリの.venvへのジャンクションをworktree内に作成する

    worktreeは新規git checkoutのため依存関係がインストールされていない。
    絶対パスでworktree外へアクセスする代わりに、worktree内の相対パス
    （./.venv）で本体の仮想環境を使えるようにする。失敗してもテストが
    動かせないだけなので、サブタスク作成自体は失敗させない。
    """
    venv_source = Path(repo_path) / ".venv"
    venv_link = Path(worktree_path) / ".venv"
    if not venv_source.exists() or venv_link.exists():
        return
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(venv_link), str(venv_source)],
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_SECONDS,
    )


def commit_subtask_instruction(worktree_path: str, title: str, instruction: str) -> None:
    subtask_dir = Path(worktree_path) / ".claude-tower"
    subtask_dir.mkdir(parents=True, exist_ok=True)
    (subtask_dir / "subtask.md").write_text(
        f"# サブタスク: {title}\n\n{instruction}\n",
        encoding="utf-8",
    )
    _run_git(["add", ".claude-tower/subtask.md"], cwd=worktree_path)
    _run_git(["commit", "-m", f"[サブタスク] {title} ― 指示を記録"], cwd=worktree_path)


def append_instruction_history(worktree_path: str, instruction: str) -> None:
    subtask_dir = Path(worktree_path) / ".claude-tower"
    subtask_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    entry = f"## 実行指示（{timestamp}）\n\n{instruction}\n\n"
    with (subtask_dir / "subtask.md").open("a", encoding="utf-8") as f:
        f.write(entry)
    _run_git(["add", ".claude-tower/subtask.md"], cwd=worktree_path)
    _run_git(["commit", "-m", "[サブタスク] 指示内容を記録"], cwd=worktree_path)


def push_branch(worktree_path: str, branch_name: str) -> None:
    _run_git(["push", "-u", "origin", branch_name], cwd=worktree_path)


def pull_latest(repo_path: str, branch: str) -> None:
    _run_git(["pull", "origin", branch], cwd=repo_path)


def has_remote_updates(repo_path: str, branch: str) -> bool:
    """リモートブランチに、チェックアウト中のHEADへ未取り込みのコミットがあるか

    判定前にリモートの最新を取得する。
    """
    _run_git(["fetch", "origin", branch], cwd=repo_path)
    count = _run_git(["rev-list", "--count", f"HEAD..origin/{branch}"], cwd=repo_path)
    return int(count.strip()) > 0


def is_commit_in_head(repo_path: str, commit: str) -> bool:
    """コミットがチェックアウト中のHEADに含まれるか

    ローカルに存在しないコミットは含まれないとみなす。
    """
    try:
        _run_git(["merge-base", "--is-ancestor", commit, "HEAD"], cwd=repo_path)
    except GitClientError:
        return False
    return True


def prepare_detached_worktree(repo_path: str, worktree_path: str, branch: str) -> None:
    """リモートブランチの最新をdetached HEADでworktreeに用意する

    対象ブランチは別worktreeでチェックアウト中の場合があるため、
    ブランチを作らずdetached HEADで扱う。
    worktreeが既にあれば再利用し、途中のマージ状態は破棄する。
    """
    _run_git(["fetch", "origin"], cwd=repo_path)
    target = f"origin/{branch}"
    if Path(worktree_path).exists():
        _run_git(["checkout", "--force", "--detach", target], cwd=worktree_path)
    else:
        _run_git(["worktree", "add", "--detach", worktree_path, target], cwd=repo_path)
    link_shared_venv(repo_path, worktree_path)


def merge_remote_branch(worktree_path: str, branch: str, message: str) -> bool:
    """origin/{branch}をマージし、競合なく完了したかを返す

    競合した場合はマージ途中の状態のまま残す。
    """
    try:
        _run_git(["merge", "--no-ff", "-m", message, f"origin/{branch}"], cwd=worktree_path)
    except GitClientError:
        if not list_unmerged_files(worktree_path):
            raise
        return False
    return True


def list_unmerged_files(worktree_path: str) -> list[str]:
    output = _run_git(["diff", "--name-only", "--diff-filter=U"], cwd=worktree_path)
    return [line for line in output.splitlines() if line]


def is_merge_in_progress(worktree_path: str) -> bool:
    try:
        _run_git(["rev-parse", "-q", "--verify", "MERGE_HEAD"], cwd=worktree_path)
    except GitClientError:
        return False
    return True


def commit_merge(worktree_path: str) -> None:
    _run_git(["commit", "--no-edit"], cwd=worktree_path)


def push_head_to(worktree_path: str, branch: str) -> None:
    _run_git(["push", "origin", f"HEAD:refs/heads/{branch}"], cwd=worktree_path)
