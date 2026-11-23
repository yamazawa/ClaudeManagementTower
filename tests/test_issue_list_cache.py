import json
import subprocess
from datetime import datetime, timezone

import pytest

from core import github_client
from core.github_client import GitHubClientError
from core.issue_list_cache import IssueListCache

TTL = 45.0


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _loader(calls: list, result: list[dict]):
    def load():
        calls.append(1)
        return result

    return load


def _cache(clock, ttl=TTL):
    return IssueListCache(lambda: ttl, clock)


def test_returns_cached_result_within_ttl():
    clock, calls = _Clock(), []
    cache = _cache(clock)
    load = _loader(calls, [{"number": 1}])

    cache.get_or_load(("owner/repo", "open"), load)
    clock.now += TTL - 1
    result = cache.get_or_load(("owner/repo", "open"), load)

    assert (result, len(calls)) == ([{"number": 1}], 1)


def test_reloads_after_ttl_expires():
    clock, calls = _Clock(), []
    cache = _cache(clock)
    load = _loader(calls, [])

    cache.get_or_load(("owner/repo", "open"), load)
    clock.now += TTL
    cache.get_or_load(("owner/repo", "open"), load)

    assert len(calls) == 2


def test_keys_are_separated_by_repo_and_state():
    clock, calls = _Clock(), []
    cache = _cache(clock)
    load = _loader(calls, [])

    for key in [("a/r", "open"), ("a/r", "closed"), ("b/r", "open"), ("a/r", "open")]:
        cache.get_or_load(key, load)

    assert len(calls) == 3


def test_invalidate_repo_drops_only_that_repo():
    clock, calls = _Clock(), []
    cache = _cache(clock)
    load = _loader(calls, [])
    keys = [("a/r", "open"), ("a/r", "closed"), ("b/r", "open")]
    for key in keys:
        cache.get_or_load(key, load)

    cache.invalidate_repo("a/r")
    for key in keys:
        cache.get_or_load(key, load)

    assert len(calls) == 5


def test_zero_ttl_disables_cache():
    calls = []
    cache = _cache(_Clock(), ttl=0)
    load = _loader(calls, [])

    cache.get_or_load(("owner/repo", "open"), load)
    cache.get_or_load(("owner/repo", "open"), load)

    assert len(calls) == 2


def test_failed_load_is_not_cached():
    calls = []
    cache = _cache(_Clock())

    def fail():
        raise GitHubClientError("gh error")

    with pytest.raises(GitHubClientError):
        cache.get_or_load(("owner/repo", "open"), fail)
    cache.get_or_load(("owner/repo", "open"), _loader(calls, []))

    assert len(calls) == 1


def test_caller_mutation_does_not_affect_cache():
    cache = _cache(_Clock())
    load = _loader([], [{"number": 1}])

    cache.get_or_load(("owner/repo", "open"), load)[0]["number"] = 99

    assert cache.get_or_load(("owner/repo", "open"), load) == [{"number": 1}]


@pytest.fixture
def gh_calls(monkeypatch):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        stdout = json.dumps([{"number": 1}]) if args[2] == "list" else ""
        if args[2] == "create":
            stdout = "https://github.com/owner/repo/issues/2"
        return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(github_client.subprocess, "run", run)
    return calls


def _list_count(calls):
    return sum(1 for args in calls if args[2] == "list")


def test_list_issues_uses_cache(gh_calls):
    github_client.list_issues("owner/repo", "open")
    github_client.list_issues("owner/repo", "open")

    assert _list_count(gh_calls) == 1


def test_list_issues_closed_since_uses_cache_per_since(gh_calls):
    since = datetime(2026, 11, 23, tzinfo=timezone.utc)
    github_client.list_issues_closed_since("owner/repo", since)
    github_client.list_issues_closed_since("owner/repo", since)
    github_client.list_issues_closed_since("owner/repo", since.replace(day=24))

    assert _list_count(gh_calls) == 2


@pytest.mark.parametrize(
    "mutate",
    [
        lambda: github_client.create_issue("owner/repo", "t", "b"),
        lambda: github_client.edit_issue_title("owner/repo", 1, "t"),
        lambda: github_client.close_issue("owner/repo", 1),
        lambda: github_client.reopen_issue("owner/repo", 1),
    ],
)
def test_issue_change_invalidates_cache(gh_calls, mutate):
    github_client.list_issues("owner/repo", "open")
    mutate()
    github_client.list_issues("owner/repo", "open")

    assert _list_count(gh_calls) == 2


def test_failed_issue_change_keeps_cache(gh_calls, monkeypatch):
    github_client.list_issues("owner/repo", "open")
    monkeypatch.setattr(
        github_client.subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 1, stdout="", stderr="not found"),
    )

    with pytest.raises(GitHubClientError):
        github_client.close_issue("owner/repo", 1)
    assert github_client.list_issues("owner/repo", "open") == [{"number": 1}]
