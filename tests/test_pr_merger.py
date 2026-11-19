import pytest

from core import pr_merger
from core.pr_merger import PrMergeError, merge_pr_with_update, resolve_conflicts_with_claude

PR = {"number": 7, "headRefName": "feature", "baseRefName": "master"}


@pytest.fixture
def calls(monkeypatch):
    recorded = []
    monkeypatch.setattr(pr_merger.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(pr_merger, "merge_pull_request", lambda repo, number: recorded.append(("merge", number)))
    monkeypatch.setattr(
        pr_merger, "update_pr_branch", lambda repo_path, worktree, pr: recorded.append(("update", worktree))
    )
    return recorded


def _states(monkeypatch, states):
    iterator = iter(states)
    monkeypatch.setattr(pr_merger, "get_pr_mergeable", lambda repo, number: next(iterator))


def test_mergeable_pr_is_merged_directly(monkeypatch, calls):
    _states(monkeypatch, ["UNKNOWN", "MERGEABLE"])

    merge_pr_with_update("o/r", "repo", "base", PR)

    assert calls == [("merge", 7)]


def test_conflicting_pr_is_updated_before_merge(monkeypatch, calls, tmp_path):
    _states(monkeypatch, ["CONFLICTING", "UNKNOWN", "MERGEABLE"])

    merge_pr_with_update("o/r", "repo", str(tmp_path), PR)

    assert calls == [("update", str(tmp_path / "merge-pr-7")), ("merge", 7)]


def test_still_conflicting_after_update_raises(monkeypatch, calls):
    monkeypatch.setattr(pr_merger, "get_pr_mergeable", lambda repo, number: "CONFLICTING")
    clock = iter([0, 0, 1000, 1000])
    monkeypatch.setattr(pr_merger.time, "monotonic", lambda: next(clock))

    with pytest.raises(PrMergeError):
        merge_pr_with_update("o/r", "repo", "base", PR)
    assert ("merge", 7) not in calls


def test_stale_conflicting_state_right_after_push_is_retried(monkeypatch, calls, tmp_path):
    # push直後、mergeableの再計算が始まる前は古いCONFLICTINGを返すことがある
    _states(monkeypatch, ["CONFLICTING", "CONFLICTING", "MERGEABLE"])

    merge_pr_with_update("o/r", "repo", str(tmp_path), PR)

    assert calls == [("update", str(tmp_path / "merge-pr-7")), ("merge", 7)]


def _fake_claude(monkeypatch, unmerged_after: list[str], merge_in_progress: bool):
    unmerged = iter([["a.txt"], unmerged_after])
    monkeypatch.setattr(pr_merger, "list_unmerged_files", lambda path: next(unmerged))
    prompts = []

    async def run_claude(prompt, worktree, policy_prompt):
        prompts.append(prompt)
        return None, None

    monkeypatch.setattr(pr_merger, "run_claude", run_claude)
    monkeypatch.setattr(pr_merger, "is_merge_in_progress", lambda path: merge_in_progress)
    committed = []
    monkeypatch.setattr(pr_merger, "commit_merge", committed.append)
    return prompts, committed


def test_resolved_conflict_is_committed(monkeypatch, tmp_path):
    (tmp_path / "a.txt").write_text("resolved\n", encoding="utf-8")
    prompts, committed = _fake_claude(monkeypatch, [], merge_in_progress=True)

    resolve_conflicts_with_claude(str(tmp_path), PR)

    assert "- a.txt" in prompts[0]
    assert committed == [str(tmp_path)]


def test_commit_skipped_when_claude_already_committed(monkeypatch, tmp_path):
    (tmp_path / "a.txt").write_text("resolved\n", encoding="utf-8")
    _, committed = _fake_claude(monkeypatch, [], merge_in_progress=False)

    resolve_conflicts_with_claude(str(tmp_path), PR)

    assert committed == []


def test_unresolved_conflict_raises(monkeypatch, tmp_path):
    _, committed = _fake_claude(monkeypatch, ["a.txt"], merge_in_progress=True)

    with pytest.raises(PrMergeError):
        resolve_conflicts_with_claude(str(tmp_path), PR)
    assert committed == []


def test_leftover_conflict_marker_raises(monkeypatch, tmp_path):
    (tmp_path / "a.txt").write_text("<<<<<<< HEAD\nx\n=======\ny\n>>>>>>> origin/master\n", encoding="utf-8")
    _, committed = _fake_claude(monkeypatch, [], merge_in_progress=True)

    with pytest.raises(PrMergeError):
        resolve_conflicts_with_claude(str(tmp_path), PR)
    assert committed == []
