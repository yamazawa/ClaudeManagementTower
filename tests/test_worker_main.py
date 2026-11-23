from types import SimpleNamespace

import pytest

import worker.main as worker_main

LIMIT_MESSAGE = "You've hit your 5-hour limit · resets 10pm (exit code: 1)"
ORIGINAL_IS_RATE_LIMITED = worker_main._is_rate_limited


@pytest.fixture(autouse=True)
def not_rate_limited(monkeypatch):
    monkeypatch.setattr(worker_main, "_is_rate_limited", lambda: False)


def test_run_loop_exits_when_own_row_removed(monkeypatch):
    calls = []
    monkeypatch.setattr(worker_main, "set_worker_state", lambda *a, **k: False)
    monkeypatch.setattr(worker_main, "claim_next_job", lambda worker_id: calls.append(worker_id))

    worker_main.run_loop(1)

    assert calls == []


def test_run_loop_processes_claimed_job_then_exits_when_removed(monkeypatch):
    states = iter([True, False])
    processed = []
    monkeypatch.setattr(worker_main, "set_worker_state", lambda *a, **k: next(states))
    monkeypatch.setattr(worker_main, "_cleanup_stale_records", lambda: None)
    monkeypatch.setattr(worker_main, "claim_next_job", lambda worker_id: {"job_id": 5, "subtask_id": 1})
    monkeypatch.setattr(worker_main, "process_job", lambda job, worker_id: processed.append(job["job_id"]))

    worker_main.run_loop(1)

    assert processed == [5]


def test_run_claude_for_job_records_rate_limit_event(monkeypatch):
    from claude_agent_sdk import RateLimitEvent, RateLimitInfo

    info = RateLimitInfo(status="allowed", rate_limit_type="five_hour", utilization=0.3)
    recorded = []

    async def fake_run_claude(prompt, worktree, resume=None, on_message=None):
        on_message(RateLimitEvent(rate_limit_info=info, uuid="u", session_id="s"))
        on_message(object())
        return "s", "done"

    monkeypatch.setattr(worker_main, "run_claude", fake_run_claude)
    monkeypatch.setattr(worker_main, "record_event", lambda *a, **k: None)
    monkeypatch.setattr(worker_main, "record_rate_limit", recorded.append)

    assert worker_main._run_claude_for_job(1, "wt", "prompt", None) == ("s", "done")
    assert recorded == [info]


def _run_failing_job(monkeypatch, message: str) -> list:
    finished = []

    def failing(*args):
        raise RuntimeError(message)

    monkeypatch.setattr(worker_main, "set_worker_state", lambda *a, **k: True)
    subtask = SimpleNamespace(instruction="指示")
    monkeypatch.setattr(worker_main, "_load_subtask_and_project", lambda subtask_id: (subtask, object()))
    monkeypatch.setattr(worker_main, "record_event", lambda *a, **k: None)
    monkeypatch.setattr(worker_main, "_run_with_heartbeat", failing)
    monkeypatch.setattr(worker_main, "finish_job", lambda job_id, status, exit_code: finished.append(status))
    worker_main.process_job({"job_id": 1, "subtask_id": 1}, 1)
    return finished


def test_process_job_marks_rate_limited_on_limit_error(monkeypatch):
    assert _run_failing_job(monkeypatch, LIMIT_MESSAGE) == ["rate_limited"]


def test_process_job_marks_failed_on_other_error(monkeypatch):
    assert _run_failing_job(monkeypatch, "boom") == ["failed"]


@pytest.mark.parametrize(
    ("resets_at", "expected", "requeued"),
    [(None, False, True), (4102444800, True, False)],
)
def test_is_rate_limited_requeues_only_after_reset(monkeypatch, resets_at, expected, requeued):
    calls = []
    monkeypatch.setattr(worker_main, "blocked_until", lambda: resets_at)
    monkeypatch.setattr(worker_main, "requeue_rate_limited_jobs", lambda delay: calls.append(delay) or [])

    assert ORIGINAL_IS_RATE_LIMITED() is expected
    assert bool(calls) is requeued


def _finalize_targets(monkeypatch, events: list):
    monkeypatch.setattr(worker_main, "save_report", lambda *a, **k: "report.html")
    monkeypatch.setattr(worker_main, "record_event", lambda job_id, **k: events.append(k))
    subtask = SimpleNamespace(id=1, github_pr_number=9)
    project = SimpleNamespace(github_repo="owner/repo")
    return subtask, project


def test_finalize_success_returns_needs_attention_when_mark_ready_fails(monkeypatch):
    from core.github_client import GitHubClientError

    events = []
    subtask, project = _finalize_targets(monkeypatch, events)

    def fail(repo, number):
        raise GitHubClientError("TLS handshake timeout")

    monkeypatch.setattr(worker_main, "mark_pr_ready", fail)
    monkeypatch.setattr(worker_main, "SessionLocal", lambda: pytest.fail("not expected"))

    assert worker_main._finalize_success(1, subtask, project, "wt", "done") == "needs_attention"
    assert events[-1]["event_type"] == "error"
    assert "TLS handshake timeout" in events[-1]["content"]


def test_finalize_success_marks_resolved_when_mark_ready_succeeds(monkeypatch):
    events = []
    subtask, project = _finalize_targets(monkeypatch, events)
    db_subtask = SimpleNamespace(lifecycle_state=None)

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get(self, model, key):
            return db_subtask

        def commit(self):
            pass

    monkeypatch.setattr(worker_main, "mark_pr_ready", lambda repo, number: None)
    monkeypatch.setattr(worker_main, "SessionLocal", FakeSession)

    assert worker_main._finalize_success(1, subtask, project, "wt", "done") == "succeeded"
    assert db_subtask.lifecycle_state == worker_main.LifecycleState.RESOLVED
