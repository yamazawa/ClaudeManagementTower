"""リポジトリの表示情報

Claude管理塔の画面で使うリポジトリ番号と表示名を定義する。
キーはGitHubの「owner/repo」形式とする。
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class RepoInfo:
    number: int
    display_name: str


REPO_CATALOG: dict[str, RepoInfo] = {
    "yamazawa/ClaudeManagementTower": RepoInfo(number=1, display_name="Claude監視塔"),
    "yamazawa/claude-tower-test-repo": RepoInfo(number=2, display_name="検証用リポジトリ"),
}


def describe_repo(github_repo: str, fallback_name: str) -> dict:
    """リポジトリの表示情報

    辞書に無いリポジトリは番号なし・登録名で表示する。
    """
    info = REPO_CATALOG.get(github_repo)
    return {
        "repo_number": info.number if info else None,
        "display_name": info.display_name if info else fallback_name,
        "repo_url": f"https://github.com/{github_repo}",
    }
