import logging
from contextlib import contextmanager

from core import logging_config


@contextmanager
def _bare_root_logger():
    """pytestが付けるハンドラを一時的に外したルートロガーを返す"""
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    root.handlers = []
    try:
        yield root
    finally:
        root.handlers = saved_handlers
        root.setLevel(saved_level)


def test_configure_logging_sets_format_and_level():
    with _bare_root_logger() as root:
        logging_config.configure_logging("warning")

        assert root.level == logging.WARNING
        assert len(root.handlers) == 1
        assert root.handlers[0].formatter._fmt == logging_config.LOG_FORMAT


def test_configure_logging_output_contains_time_name_and_level():
    record = logging.LogRecord("worker.main", logging.INFO, __file__, 1, "起動しました", None, None)
    with _bare_root_logger() as root:
        logging_config.configure_logging("INFO")
        text = root.handlers[0].format(record)

    assert "INFO [worker.main] 起動しました" in text
    assert text[:4].isdigit()


def test_configure_logging_uses_settings_level_by_default(monkeypatch):
    monkeypatch.setattr(logging_config.settings, "log_level", "debug")
    with _bare_root_logger() as root:
        logging_config.configure_logging()

        assert root.level == logging.DEBUG


def test_configure_logging_keeps_existing_handlers():
    existing = logging.NullHandler()
    with _bare_root_logger() as root:
        root.addHandler(existing)
        logging_config.configure_logging("INFO")

        assert root.handlers == [existing]
