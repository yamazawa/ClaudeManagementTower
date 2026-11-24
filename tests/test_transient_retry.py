import pytest

from core import transient_retry
from core.transient_retry import TransientError, call_with_retry, contains_any_pattern


@pytest.fixture
def sleeps(monkeypatch):
    recorded = []
    monkeypatch.setattr(transient_retry.time, "sleep", recorded.append)
    return recorded


def _operation(results: list):
    """resultsを先頭から順に返す（例外なら投げる）操作と、呼び出し回数の記録を作る"""
    calls = []

    def operation():
        calls.append(None)
        result = results[len(calls) - 1]
        if isinstance(result, Exception):
            raise result
        return result

    return operation, calls


def test_contains_any_pattern_ignores_case():
    assert contains_any_pattern("fatal: Could Not Resolve Host", ("could not resolve host",))
    assert not contains_any_pattern("fatal: not found", ("could not resolve host",))


def test_call_with_retry_returns_after_transient_error(sleeps):
    operation, calls = _operation([TransientError("e"), "ok"])

    assert call_with_retry(operation, 3, 2) == "ok"
    assert len(calls) == 2
    assert sleeps == [2]


def test_call_with_retry_extends_interval_and_gives_up(sleeps):
    operation, calls = _operation([TransientError("e1"), TransientError("e2"), TransientError("e3")])

    with pytest.raises(TransientError, match="e3"):
        call_with_retry(operation, 3, 2)
    assert len(calls) == 3
    assert sleeps == [2, 4]


def test_call_with_retry_does_not_retry_other_errors(sleeps):
    operation, calls = _operation([ValueError("permanent"), "ok"])

    with pytest.raises(ValueError):
        call_with_retry(operation, 3, 2)
    assert len(calls) == 1
    assert sleeps == []


def test_call_with_retry_single_attempt_does_not_retry(sleeps):
    operation, calls = _operation([TransientError("e"), "ok"])

    with pytest.raises(TransientError):
        call_with_retry(operation, 1, 2)
    assert len(calls) == 1
