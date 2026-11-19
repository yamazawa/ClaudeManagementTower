import json

import pytest

from core import claude_usage


@pytest.fixture(autouse=True)
def _clear_cache():
    claude_usage.clear_cache()
    yield
    claude_usage.clear_cache()


def test_read_access_token(tmp_path):
    path = tmp_path / ".credentials.json"
    path.write_text(json.dumps({"claudeAiOauth": {"accessToken": "token-1"}}), encoding="utf-8")

    assert claude_usage.read_access_token(path) == "token-1"


def test_read_access_token_returns_none_when_missing(tmp_path):
    assert claude_usage.read_access_token(tmp_path / "none.json") is None


def test_read_access_token_returns_none_when_invalid(tmp_path):
    path = tmp_path / ".credentials.json"
    path.write_text("{}", encoding="utf-8")

    assert claude_usage.read_access_token(path) is None


def test_normalize_window_converts_percent_and_time():
    window = {"utilization": 50.0, "resets_at": "1970-01-01T00:01:40.5Z"}

    assert claude_usage.normalize_window(window) == {"utilization": 0.5, "resets_at": 100}


@pytest.mark.parametrize("window", [None, {}, {"utilization": None}])
def test_normalize_window_returns_none_without_utilization(window):
    assert claude_usage.normalize_window(window) is None


def test_fetch_usage_returns_none_without_token():
    def requester(token):
        raise AssertionError("呼ばれない")

    assert claude_usage.fetch_usage(lambda: None, requester) is None


def test_fetch_usage_returns_none_on_error():
    def requester(token):
        raise OSError("network")

    assert claude_usage.fetch_usage(lambda: "t", requester) is None


def test_fetch_usage_passes_token():
    assert claude_usage.fetch_usage(lambda: "t", lambda token: {"token": token}) == {"token": "t"}


def test_get_usage_caches_within_ttl(monkeypatch):
    monkeypatch.setattr(claude_usage.settings, "claude_usage_cache_seconds", 60)
    calls = []

    def fetcher():
        calls.append(1)
        return {"n": len(calls)}

    assert claude_usage.get_usage(fetcher, lambda: 0) == {"n": 1}
    assert claude_usage.get_usage(fetcher, lambda: 59) == {"n": 1}
    assert claude_usage.get_usage(fetcher, lambda: 61) == {"n": 2}


def test_credentials_path_uses_setting(monkeypatch, tmp_path):
    monkeypatch.setattr(claude_usage.settings, "claude_credentials_path", str(tmp_path / "c.json"))

    assert claude_usage.credentials_path() == tmp_path / "c.json"


def test_credentials_path_uses_config_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(claude_usage.settings, "claude_credentials_path", "")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))

    assert claude_usage.credentials_path() == tmp_path / ".credentials.json"
