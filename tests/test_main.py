"""Unit tests for main._configure_logging: verifies the root logger is wired
to a real file handler so log records land somewhere retrievable in a
packaged, windowed (no console) build.
"""

import logging
import logging.handlers

import pytest

from main import _configure_logging


@pytest.fixture
def _clean_root_logger():
    """Snapshots root logger handlers/level and restores them afterward.

    ``_configure_logging`` mutates process-global logging state (the root
    logger), so without this fixture a test run here would leak an open
    FileHandler pointing at a deleted tmp_path into every other test.
    """
    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    original_level = root_logger.level
    try:
        yield root_logger
    finally:
        for handler in list(root_logger.handlers):
            if handler not in original_handlers:
                root_logger.removeHandler(handler)
                handler.close()
        root_logger.setLevel(original_level)


def test_configure_logging_writes_records_to_log_file_in_given_dir(
    tmp_path, _clean_root_logger
) -> None:
    _configure_logging(log_dir=tmp_path)

    logging.getLogger("some.module").info("hello from the test suite")
    for handler in logging.getLogger().handlers:
        handler.flush()

    log_file = tmp_path / "time_clock.log"
    assert log_file.exists()
    assert "hello from the test suite" in log_file.read_text(encoding="utf-8")


def test_configure_logging_sets_root_level_to_info(
    tmp_path, _clean_root_logger
) -> None:
    _configure_logging(log_dir=tmp_path)

    assert logging.getLogger().getEffectiveLevel() == logging.INFO


def test_configure_logging_attaches_rotating_file_handler_with_size_limits(
    tmp_path, _clean_root_logger
) -> None:
    """A plain FileHandler would let time_clock.log grow unbounded for the
    lifetime of an always-running system-tray app; it must be a
    RotatingFileHandler with sane rotation limits instead.
    """
    _configure_logging(log_dir=tmp_path)

    handlers = [
        handler
        for handler in logging.getLogger().handlers
        if isinstance(handler, logging.handlers.RotatingFileHandler)
    ]
    assert len(handlers) == 1
    handler = handlers[0]
    assert handler.maxBytes == 5 * 1024 * 1024
    assert handler.backupCount == 3


def test_configure_logging_includes_timestamp_level_and_logger_name(
    tmp_path, _clean_root_logger
) -> None:
    _configure_logging(log_dir=tmp_path)

    logging.getLogger("some.module").warning("a warning message")
    for handler in logging.getLogger().handlers:
        handler.flush()

    line = (tmp_path / "time_clock.log").read_text(encoding="utf-8").strip()
    assert "WARNING" in line
    assert "some.module" in line
    assert "a warning message" in line
