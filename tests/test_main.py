"""Unit tests for main._configure_logging and main.main()'s error-handling
structure: verifies the root logger is wired to a real file handler so log
records land somewhere retrievable in a packaged, windowed (no console)
build, and that main() fails gracefully (rather than crashing with an
unhandled traceback) both when logging setup itself fails and when a
non-essential boot step (open-record checks / tray icon) fails after the
main window is already built.
"""

import logging
import logging.handlers
from unittest import mock

import pytest

import main
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


def test_main_shows_dialog_and_exits_when_configure_logging_fails(monkeypatch) -> None:
    """If _configure_logging() itself raises (e.g. an unwritable app-data
    directory), main() must not let the exception propagate unhandled --
    logging isn't up yet at that point, so there is nothing to log, but a
    messagebox must still be shown and the process must exit cleanly
    instead of crashing with a bare traceback (invisible in a packaged,
    windowed/no-console build).
    """
    monkeypatch.setattr(
        main, "_configure_logging", mock.Mock(side_effect=OSError("no permission"))
    )
    show_error = mock.Mock()
    monkeypatch.setattr(main.messagebox, "showerror", show_error)
    monkeypatch.setattr(main.sys, "exit", mock.Mock(side_effect=SystemExit(1)))
    # If the early-exit guard were broken, execution would fall through to
    # Database() -- fail loudly rather than silently doing real DB/UI work.
    monkeypatch.setattr(
        main, "Database", mock.Mock(side_effect=AssertionError("should not be reached"))
    )

    with pytest.raises(SystemExit):
        main.main()

    show_error.assert_called_once()
    title, message = show_error.call_args[0]
    assert "Startup Failed" in title
    assert "logging" in message.lower()
    main.sys.exit.assert_called_once_with(1)


def _patch_successful_boot(monkeypatch) -> mock.Mock:
    """Patches every collaborator main() touches while building the main
    window so it can run start-to-finish under pytest's headless/no-X
    environment, and returns the mocked ``root`` (a stand-in ``tk.Tk()``
    instance) so tests can assert on ``mainloop``/``destroy`` calls.
    """
    root = mock.MagicMock(name="root")
    monkeypatch.setattr(main.tk, "Tk", mock.Mock(return_value=root))
    monkeypatch.setattr(main, "Database", mock.Mock())
    monkeypatch.setattr(main, "SettingsManager", mock.Mock())
    monkeypatch.setattr(main, "EventBus", mock.Mock())
    monkeypatch.setattr(main, "TimeClockModel", mock.Mock())
    monkeypatch.setattr(main, "VacationModel", mock.Mock())
    monkeypatch.setattr(main, "SicknessModel", mock.Mock())
    monkeypatch.setattr(main, "MiliuimModel", mock.Mock())
    monkeypatch.setattr(main, "TimeClockController", mock.Mock())
    monkeypatch.setattr(main, "VacationController", mock.Mock())
    monkeypatch.setattr(main, "SicknessController", mock.Mock())
    monkeypatch.setattr(main, "MiliuimController", mock.Mock())
    monkeypatch.setattr(main, "resolve_theme_mode", mock.Mock(return_value="light"))
    monkeypatch.setattr(main, "apply_theme", mock.Mock())
    monkeypatch.setattr(main, "MainWindow", mock.Mock())
    monkeypatch.setattr(main, "TimeClockTab", mock.Mock())
    monkeypatch.setattr(main, "VacationTab", mock.Mock())
    monkeypatch.setattr(main, "SicknessTab", mock.Mock())
    monkeypatch.setattr(main, "MiliuimTab", mock.Mock())
    monkeypatch.setattr(main, "SystemTray", mock.Mock())
    monkeypatch.setattr(main, "_boot_checks", mock.Mock())
    monkeypatch.setattr(main, "_configure_logging", mock.Mock())
    monkeypatch.setattr(main.messagebox, "showerror", mock.Mock())
    monkeypatch.setattr(main.messagebox, "showwarning", mock.Mock())
    return root


@pytest.mark.parametrize("failing_target", ["_boot_checks", "SystemTray"])
def test_main_survives_boot_check_or_tray_failure(monkeypatch, failing_target) -> None:
    """A failure in _boot_checks() or SystemTray/tray.start() happens after
    the main window and all tabs are already fully constructed. It must be
    treated as non-fatal: the main window must still reach mainloop() (i.e.
    not be destroyed / torn down) and the failure must be surfaced via a
    warning dialog rather than the fatal "Startup Failed" error dialog used
    for core window/tab-construction failures.
    """
    root = _patch_successful_boot(monkeypatch)
    monkeypatch.setattr(
        main, failing_target, mock.Mock(side_effect=RuntimeError("boom"))
    )

    main.main()

    root.destroy.assert_not_called()
    root.mainloop.assert_called_once()
    main.messagebox.showwarning.assert_called_once()
    main.messagebox.showerror.assert_not_called()
