"""Tests for VacationRecordDialog._update_hours_cap (no Tk mainloop needed).

Mirrors the ``__new__``-bypass pattern used in tests/views/test_report_dialog.py:
the dialog's Tk widgets (spinbox, hint label, hours var) are stood in with
MagicMocks so the method under test can run without a live Tk interpreter or
display, matching this repo's headless-CI constraint (see the module
docstring in tests/views/test_help_viewer_dialogs.py).
"""
import logging
import sqlite3
from datetime import date
from unittest import mock

import pytest

from views.vacation_record_dialog import VacationRecordDialog


def _make_dialog(model, get_date, hours_text="8.0"):
    dialog = VacationRecordDialog.__new__(VacationRecordDialog)
    dialog._model = model
    dialog._get_date = get_date
    dialog._spn_hours = mock.MagicMock()
    dialog._lbl_hours_hint = mock.MagicMock()
    dialog._var_hours = mock.MagicMock()
    dialog._var_hours.get.return_value = hours_text
    return dialog


def test_update_hours_cap_happy_path_configures_widgets() -> None:
    model = mock.MagicMock()
    model.get_daily_target_for_date.return_value = 6.0
    dialog = _make_dialog(model, lambda: date(2026, 6, 1))

    dialog._update_hours_cap()

    dialog._spn_hours.config.assert_called_once_with(to=6.0)
    dialog._lbl_hours_hint.config.assert_called_once_with(
        text="(max 6.0h for this day)")


def test_update_hours_cap_clamps_current_value_above_new_cap() -> None:
    model = mock.MagicMock()
    model.get_daily_target_for_date.return_value = 4.0
    dialog = _make_dialog(model, lambda: date(2026, 6, 1), hours_text="8.0")

    dialog._update_hours_cap()

    dialog._var_hours.set.assert_called_once_with("4.0")


def test_update_hours_cap_zero_target_falls_back_to_eight() -> None:
    """A day-off/weekend date returns 0.0 from the model — the hint should
    still offer an 8h reference cap rather than a useless 0h spinbox."""
    model = mock.MagicMock()
    model.get_daily_target_for_date.return_value = 0.0
    dialog = _make_dialog(model, lambda: date(2026, 6, 6))

    dialog._update_hours_cap()

    dialog._spn_hours.config.assert_called_once_with(to=8.0)


def test_update_hours_cap_sqlite_error_is_logged_not_swallowed_silently(
        caplog: pytest.LogCaptureFixture) -> None:
    model = mock.MagicMock()
    model.get_daily_target_for_date.side_effect = sqlite3.OperationalError(
        "database is locked")
    dialog = _make_dialog(model, lambda: date(2026, 6, 1))

    with caplog.at_level(logging.WARNING, logger="views.vacation_record_dialog"):
        dialog._update_hours_cap()  # must not raise

    # The hint just doesn't update — acceptable UX for this rare failure —
    # but it must show up in the log instead of vanishing into `except: pass`.
    dialog._spn_hours.config.assert_not_called()
    assert any(record.levelno >= logging.WARNING for record in caplog.records)


def test_update_hours_cap_bad_date_is_logged_and_skips_db_lookup(
        caplog: pytest.LogCaptureFixture) -> None:
    model = mock.MagicMock()

    def _bad_get_date() -> date:
        raise ValueError("no valid date selected")

    dialog = _make_dialog(model, _bad_get_date)

    with caplog.at_level(logging.WARNING, logger="views.vacation_record_dialog"):
        dialog._update_hours_cap()  # must not raise

    model.get_daily_target_for_date.assert_not_called()
    assert any(record.levelno >= logging.WARNING for record in caplog.records)


def test_update_hours_cap_non_sqlite_error_propagates() -> None:
    """A real code bug (not a DB failure) must not be silently swallowed —
    it should propagate so Tk's report_callback_exception handler can
    surface it, consistent with the narrowed exception handling elsewhere
    in this codebase-review pass."""
    model = mock.MagicMock()
    model.get_daily_target_for_date.side_effect = AttributeError("boom")
    dialog = _make_dialog(model, lambda: date(2026, 6, 1))

    with pytest.raises(AttributeError):
        dialog._update_hours_cap()
