from claude_agent_sdk import RateLimitInfo
from sqlalchemy.orm import sessionmaker

from core.db import init_db, make_engine
from core.rate_limits import blocked_until, get_rate_limits, is_rate_limit_error, record_rate_limit


# 2100-01-01T00:00:00Z（未来のリセット時刻）
FUTURE = 4102444800


def _no_usage():
    return None


def _session_factory(tmp_path):
    engine = make_engine(str(tmp_path / "test.db"))
    init_db(bind=engine)
    return sessionmaker(bind=engine)


def test_get_rate_limits_returns_none_when_not_received(tmp_path):
    factory = _session_factory(tmp_path)

    assert get_rate_limits(factory, _no_usage) == {"five_hour": None, "seven_day": None}


def test_record_rate_limit_overwrites_same_type(tmp_path):
    factory = _session_factory(tmp_path)
    record_rate_limit(RateLimitInfo(status="allowed", rate_limit_type="five_hour", utilization=0.2, resets_at=FUTURE), factory)
    record_rate_limit(RateLimitInfo(status="allowed_warning", rate_limit_type="five_hour", utilization=0.8, resets_at=FUTURE + 100), factory)

    five_hour = get_rate_limits(factory, _no_usage)["five_hour"]

    assert five_hour["status"] == "allowed_warning"
    assert five_hour["utilization"] == 0.8
    assert five_hour["resets_at"] == FUTURE + 100


def test_record_rate_limit_keeps_types_separately(tmp_path):
    factory = _session_factory(tmp_path)
    record_rate_limit(RateLimitInfo(status="allowed", rate_limit_type="five_hour", utilization=0.1), factory)
    record_rate_limit(RateLimitInfo(status="allowed", rate_limit_type="seven_day", utilization=0.5), factory)

    limits = get_rate_limits(factory, _no_usage)

    assert limits["five_hour"]["utilization"] == 0.1
    assert limits["seven_day"]["utilization"] == 0.5


def test_record_rate_limit_ignores_info_without_type(tmp_path):
    factory = _session_factory(tmp_path)

    assert record_rate_limit(RateLimitInfo(status="allowed"), factory) is False
    assert get_rate_limits(factory, _no_usage) == {"five_hour": None, "seven_day": None}


def test_get_rate_limits_prefers_usage_api(tmp_path):
    factory = _session_factory(tmp_path)
    record_rate_limit(RateLimitInfo(status="allowed_warning", rate_limit_type="five_hour", utilization=0.2, resets_at=FUTURE), factory)
    usage = {"five_hour": {"utilization": 35.0, "resets_at": "2100-01-01T00:16:40+00:00"}, "seven_day": None}

    limits = get_rate_limits(factory, lambda: usage)

    assert limits["five_hour"]["status"] == "allowed_warning"
    assert limits["five_hour"]["utilization"] == 0.35
    assert limits["five_hour"]["resets_at"] == FUTURE + 1000
    assert limits["seven_day"] is None


def test_get_rate_limits_drops_status_of_past_window(tmp_path):
    factory = _session_factory(tmp_path)
    record_rate_limit(RateLimitInfo(status="allowed_warning", rate_limit_type="five_hour", utilization=0.9, resets_at=100), factory)
    usage = {"five_hour": {"utilization": 0.0, "resets_at": None}}

    assert get_rate_limits(factory, lambda: usage)["five_hour"]["status"] is None
    assert get_rate_limits(factory, _no_usage)["five_hour"]["status"] is None


def test_get_rate_limits_judges_status_without_resets_by_window_start(tmp_path):
    factory = _session_factory(tmp_path)
    record_rate_limit(RateLimitInfo(status="allowed_warning", rate_limit_type="five_hour"), factory)
    usage = {"five_hour": {"utilization": 80.0, "resets_at": "2100-01-01T00:00:00Z"}}

    # 受信時刻が現在の枠の開始より前のため前の枠の状態とみなす
    assert get_rate_limits(factory, lambda: usage)["five_hour"]["status"] is None
    assert get_rate_limits(factory, _no_usage)["five_hour"]["status"] == "allowed_warning"


def test_get_rate_limits_drops_status_without_resets_when_window_not_started(tmp_path):
    factory = _session_factory(tmp_path)
    record_rate_limit(RateLimitInfo(status="allowed_warning", rate_limit_type="five_hour"), factory)
    usage = {"five_hour": {"utilization": 0.0, "resets_at": None}}

    assert get_rate_limits(factory, lambda: usage)["five_hour"]["status"] is None


def test_get_rate_limits_marks_rejected_when_usage_full(tmp_path):
    factory = _session_factory(tmp_path)
    record_rate_limit(RateLimitInfo(status="allowed_warning", rate_limit_type="five_hour", resets_at=FUTURE), factory)
    usage = {"five_hour": {"utilization": 100.0, "resets_at": None}, "seven_day": {"utilization": 100.0, "resets_at": None}}

    limits = get_rate_limits(factory, lambda: usage)

    assert limits["five_hour"]["status"] == "rejected"
    assert limits["seven_day"]["status"] == "rejected"


def test_get_rate_limits_uses_usage_api_without_event(tmp_path):
    factory = _session_factory(tmp_path)
    usage = {"seven_day": {"utilization": 12.0, "resets_at": None}}

    seven_day = get_rate_limits(factory, lambda: usage)["seven_day"]

    assert seven_day == {"status": None, "updated_at": None, "utilization": 0.12, "resets_at": None}


def test_get_rate_limits_falls_back_to_event_resets_at(tmp_path):
    factory = _session_factory(tmp_path)
    record_rate_limit(RateLimitInfo(status="allowed", rate_limit_type="five_hour", utilization=0.1, resets_at=FUTURE), factory)
    usage = {"five_hour": {"utilization": 0.0, "resets_at": None}}

    five_hour = get_rate_limits(factory, lambda: usage)["five_hour"]

    assert five_hour["utilization"] == 0.0
    assert five_hour["resets_at"] == FUTURE


def test_get_rate_limits_hides_past_event_resets_at(tmp_path):
    factory = _session_factory(tmp_path)
    record_rate_limit(RateLimitInfo(status="allowed", rate_limit_type="five_hour", utilization=0.1, resets_at=100), factory)
    usage = {"five_hour": {"utilization": 0.0, "resets_at": None}}

    assert get_rate_limits(factory, lambda: usage)["five_hour"]["resets_at"] is None
    assert get_rate_limits(factory, _no_usage)["five_hour"]["resets_at"] is None


def test_blocked_until_returns_none_without_rejection(tmp_path):
    factory = _session_factory(tmp_path)
    record_rate_limit(RateLimitInfo(status="allowed_warning", rate_limit_type="five_hour", resets_at=FUTURE), factory)

    assert blocked_until(factory) is None


def test_blocked_until_returns_latest_future_reset(tmp_path):
    factory = _session_factory(tmp_path)
    record_rate_limit(RateLimitInfo(status="rejected", rate_limit_type="five_hour", resets_at=FUTURE), factory)
    record_rate_limit(RateLimitInfo(status="rejected", rate_limit_type="seven_day_opus", resets_at=FUTURE + 100), factory)

    assert blocked_until(factory) == FUTURE + 100


def test_blocked_until_ignores_past_or_unknown_reset(tmp_path):
    factory = _session_factory(tmp_path)
    record_rate_limit(RateLimitInfo(status="rejected", rate_limit_type="five_hour", resets_at=100), factory)
    record_rate_limit(RateLimitInfo(status="rejected", rate_limit_type="seven_day"), factory)

    assert blocked_until(factory) is None


def test_is_rate_limit_error_detects_limit_messages():
    assert is_rate_limit_error("You've hit your 5-hour limit · resets 10pm (exit code: 1)")
    assert is_rate_limit_error("Claude AI usage limit reached|1700000000")
    assert not is_rate_limit_error("Command failed (exit code: 1)")
    assert not is_rate_limit_error("")
