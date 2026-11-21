"""リポジトリの表示情報

Claude管理塔の画面で使うリポジトリ表示名を定義する。
キーはGitHubの「owner/repo」形式とする。
"""

REPO_DISPLAY_NAMES: dict[str, str] = {
    "yamazawa/ClaudeManagementTower": "Claude監視塔",
    "yamazawa/claude-tower-test-repo": "検証用リポジトリ",
}


def describe_repo(github_repo: str, fallback_name: str) -> dict:
    """リポジトリの表示情報

    辞書に無いリポジトリは登録名で表示する。
    """
    return {
        "display_name": REPO_DISPLAY_NAMES.get(github_repo, fallback_name),
        "repo_url": f"https://github.com/{github_repo}",
    }
