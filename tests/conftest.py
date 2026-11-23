import pytest

from core import github_client


@pytest.fixture(autouse=True)
def _clear_issue_list_cache():
    """テスト間でIssue一覧キャッシュを持ち越さない"""
    github_client.clear_issue_list_cache()
    yield
    github_client.clear_issue_list_cache()
