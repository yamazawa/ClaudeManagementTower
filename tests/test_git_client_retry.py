import subprocess

import pytest

from core import git_client, transient_retry
from core.git_client import GitClientError

RESOLVE_ERROR = (
    "fatal: unable to access 'https://github.com/o/r.git/': Could not resolve host: github.com"
)


@pytest.fixture
def sleeps(monkeypatch):
    recorded = []
    monkeypatch.setattr(transient_retry.time, "sleep", recorded.append)
    return recorded


def _sequence_run(monkeypatch, results: list[tuple[int, str]]) -> list:
    """subprocess.runを、resultsの(終了コード, stderr)を順に返す偽物に置き換える"""
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        returncode, stderr = results[len(calls) - 1]
        return subprocess.CompletedProcess(args, returncode, stdout="ok", stderr=stderr)

    monkeypatch.setattr(git_client.subprocess, "run", run)
    return calls


def test_push_branch_retries_transient_error_then_succeeds(monkeypatch, sleeps):
    calls = _sequence_run(monkeypatch, [(128, RESOLVE_ERROR), (0, "")])

    git_client.push_branch("wt", "issue-1")

    assert calls == [["git", "push", "-u", "origin", "issue-1"]] * 2
    assert sleeps == [git_client.GIT_RETRY_INTERVAL_SECONDS]


def test_pull_latest_gives_up_after_max_attempts(monkeypatch, sleeps):
    results = [(128, "error: RPC failed; curl 56 Recv failure")] * git_client.GIT_MAX_ATTEMPTS
    calls = _sequence_run(monkeypatch, results)

    with pytest.raises(GitClientError, match="RPC failed"):
        git_client.pull_latest("repo", "master")
    assert len(calls) == git_client.GIT_MAX_ATTEMPTS
    assert len(sleeps) == git_client.GIT_MAX_ATTEMPTS - 1


def test_fetch_retries_timeout(monkeypatch, sleeps):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            raise subprocess.TimeoutExpired(args, git_client.GIT_TIMEOUT_SECONDS)
        return subprocess.CompletedProcess(args, 0, stdout="0\n", stderr="")

    monkeypatch.setattr(git_client.subprocess, "run", run)

    assert git_client.has_remote_updates("repo", "master") is False
    assert calls[:2] == [["git", "fetch", "origin", "master"]] * 2


def test_delete_remote_branch_retries_transient_error(monkeypatch, sleeps):
    calls = _sequence_run(monkeypatch, [(128, "fatal: early EOF"), (0, "")])

    git_client.delete_remote_branch("repo", "issue-1")

    assert len(calls) == 2


def test_network_operation_does_not_retry_permanent_error(monkeypatch, sleeps):
    calls = _sequence_run(monkeypatch, [(1, "! [rejected] issue-1 -> issue-1 (non-fast-forward)")])

    with pytest.raises(GitClientError, match="rejected"):
        git_client.push_head_to("wt", "issue-1")
    assert len(calls) == 1
    assert sleeps == []


def test_local_operation_does_not_retry_transient_like_error(monkeypatch, sleeps):
    calls = _sequence_run(monkeypatch, [(128, "fatal: Connection timed out"), (0, "")])

    with pytest.raises(GitClientError):
        git_client.commit_merge("wt")
    assert len(calls) == 1
    assert sleeps == []


@pytest.mark.parametrize(
    "stderr",
    [
        RESOLVE_ERROR,
        "ssh: connect to host github.com port 22: Connection timed out",
        "error: RPC failed; HTTP 502 curl 22 The requested URL returned error: 502",
        "fatal: the remote end hung up unexpectedly",
        "schannel: failed to receive handshake, SSL/TLS connection failed",
    ],
)
def test_is_transient_git_error_detects_network_errors(stderr):
    assert git_client.is_transient_git_error(stderr)


def test_is_transient_git_error_ignores_permanent_errors():
    assert not git_client.is_transient_git_error("fatal: couldn't find remote ref no-such-branch")
