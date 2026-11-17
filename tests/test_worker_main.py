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
