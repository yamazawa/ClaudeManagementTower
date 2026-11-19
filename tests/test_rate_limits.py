from claude_agent_sdk import RateLimitInfo
from sqlalchemy.orm import sessionmaker

from core.db import init_db, make_engine
from core.rate_limits import get_rate_limits, record_rate_limit


def _session_factory(tmp_path):
    engine = make_engine(str(tmp_path / "test.db"))
    init_db(bind=engine)
    return sessionmaker(bind=engine)


def test_get_rate_limits_returns_none_when_not_received(tmp_path):
    factory = _session_factory(tmp_path)

    assert get_rate_limits(factory) == {"five_hour": None, "seven_day": None}


def test_record_rate_limit_overwrites_same_type(tmp_path):
    factory = _session_factory(tmp_path)
    record_rate_limit(RateLimitInfo(status="allowed", rate_limit_type="five_hour", utilization=0.2, resets_at=100), factory)
    record_rate_limit(RateLimitInfo(status="allowed_warning", rate_limit_type="five_hour", utilization=0.8, resets_at=200), factory)

    five_hour = get_rate_limits(factory)["five_hour"]

    assert five_hour["status"] == "allowed_warning"
    assert five_hour["utilization"] == 0.8
    assert five_hour["resets_at"] == 200


def test_record_rate_limit_keeps_types_separately(tmp_path):
    factory = _session_factory(tmp_path)
    record_rate_limit(RateLimitInfo(status="allowed", rate_limit_type="five_hour", utilization=0.1), factory)
    record_rate_limit(RateLimitInfo(status="allowed", rate_limit_type="seven_day", utilization=0.5), factory)

    limits = get_rate_limits(factory)

    assert limits["five_hour"]["utilization"] == 0.1
    assert limits["seven_day"]["utilization"] == 0.5


def test_record_rate_limit_ignores_info_without_type(tmp_path):
    factory = _session_factory(tmp_path)

    assert record_rate_limit(RateLimitInfo(status="allowed"), factory) is False
    assert get_rate_limits(factory) == {"five_hour": None, "seven_day": None}
