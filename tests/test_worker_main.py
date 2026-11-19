import worker.main as worker_main


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
