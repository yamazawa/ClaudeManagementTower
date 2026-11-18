from core.repo_catalog import describe_repo


def test_describe_repo_uses_catalog():
    assert describe_repo("yamazawa/ClaudeManagementTower", "fallback") == {
        "repo_number": 1,
        "display_name": "Claude監視塔",
        "repo_url": "https://github.com/yamazawa/ClaudeManagementTower",
    }


def test_describe_repo_falls_back_for_unknown_repo():
    assert describe_repo("owner/repo", "p") == {
        "repo_number": None,
        "display_name": "p",
        "repo_url": "https://github.com/owner/repo",
    }
