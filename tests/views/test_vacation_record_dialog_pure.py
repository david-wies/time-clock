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

from domain.enums import VacationType, WarningCode
from domain.types import Result
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


def _make_dialog_for_save(get_date, raw_date_text="2026-99-99"):
    """Stand in the widgets ``_on_save`` touches on the date-parsing path."""
    dialog = VacationRecordDialog.__new__(VacationRecordDialog)
    dialog._get_date = get_date
    dialog._date_widget = mock.MagicMock()
    dialog._date_widget.get.return_value = raw_date_text
    dialog._lbl_error = mock.MagicMock()
    dialog._var_hours = mock.MagicMock()
    dialog._var_hours.get.return_value = "8.0"
    dialog._var_vtype = mock.MagicMock()
    dialog._var_vtype.get.return_value = str(VacationType.ANNUAL_LEAVE)
    dialog._var_charge = mock.MagicMock()
    dialog._var_charge.get.return_value = "1.0"
    return dialog


def test_update_hours_cap_happy_path_configures_widgets() -> None:
    model = mock.MagicMock()
    model.get_daily_target_for_date.return_value = 6.0
    dialog = _make_dialog(model, lambda: date(2026, 6, 1))

    dialog._update_hours_cap()

    dialog._spn_hours.config.assert_called_once_with(to=6.0)
    dialog._lbl_hours_hint.config.assert_called_once_with(
        text="(max 6.0h for this day)"
    )


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
    caplog: pytest.LogCaptureFixture,
) -> None:
    model = mock.MagicMock()
    model.get_daily_target_for_date.side_effect = sqlite3.OperationalError(
        "database is locked"
    )
    dialog = _make_dialog(model, lambda: date(2026, 6, 1))

    with caplog.at_level(logging.WARNING, logger="views.vacation_record_dialog"):
        dialog._update_hours_cap()  # must not raise

    # The hint just doesn't update — acceptable UX for this rare failure —
    # but it must show up in the log instead of vanishing into `except: pass`.
    dialog._spn_hours.config.assert_not_called()
    assert any(record.levelno >= logging.WARNING for record in caplog.records)


def test_update_hours_cap_bad_date_is_logged_and_skips_db_lookup(
    caplog: pytest.LogCaptureFixture,
) -> None:
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


def test_on_save_bad_date_is_logged_and_reported_as_field_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``_on_save``'s date-parsing catch was narrowed from a bare
    ``except Exception`` to ``(ValueError, IndexError)`` with logging, to
    match the standard already applied to ``_update_hours_cap``. A bad date
    must still surface as a field error, but it must also be logged instead
    of vanishing silently."""

    def _bad_get_date() -> date:
        raise ValueError("no valid date selected")

    dialog = _make_dialog_for_save(_bad_get_date, raw_date_text="2026-99-99")

    with caplog.at_level(logging.WARNING, logger="views.vacation_record_dialog"):
        dialog._on_save()  # must not raise

    dialog._lbl_error.config.assert_called_with(text="Invalid date.")
    assert any(record.levelno >= logging.WARNING for record in caplog.records)
    assert any("2026-99-99" in record.getMessage() for record in caplog.records)


def test_on_save_non_narrowed_date_error_propagates() -> None:
    """A real bug in the date widget (e.g. an ``AttributeError`` from a
    destroyed widget) must not be silently swallowed by the narrowed
    ``except (ValueError, IndexError)`` — it should propagate."""

    def _broken_get_date() -> date:
        raise AttributeError("widget destroyed")

    dialog = _make_dialog_for_save(_broken_get_date)

    with pytest.raises(AttributeError):
        dialog._on_save()


def _make_dialog_for_record_not_found() -> VacationRecordDialog:
    """Stand in every widget ``_on_save`` touches on the full success path
    (not just the date-parsing path covered by ``_make_dialog_for_save``
    above), with field values that pass every field/domain validation so
    ``_on_save`` actually reaches ``self._controller.save_record(...)`` and
    the RECORD_NOT_FOUND branch under test can be exercised.

    ``_record`` is an existing record with a non-null id (not ``None``):
    RECORD_NOT_FOUND is a stale-*edit* race — a zero-row update — so the
    branch is only reachable on the update path, and the surviving id must
    reach ``save_record``."""
    dialog = VacationRecordDialog.__new__(VacationRecordDialog)
    dialog._get_date = lambda: date(2026, 6, 1)
    dialog._lbl_error = mock.MagicMock()
    dialog._var_hours = mock.MagicMock()
    dialog._var_hours.get.return_value = "8.0"
    dialog._var_vtype = mock.MagicMock()
    dialog._var_vtype.get.return_value = str(VacationType.ANNUAL_LEAVE)
    dialog._var_note = mock.MagicMock()
    dialog._var_note.get.return_value = ""
    dialog._var_charge = mock.MagicMock()
    dialog._var_charge.get.return_value = "1.0"
    dialog._record = mock.Mock(id=123)
    dialog._controller = mock.MagicMock()
    dialog.destroy = mock.MagicMock()
    dialog.record_vanished = False
    return dialog


def test_on_save_record_not_found_sets_vanished_warns_and_destroys() -> None:
    """The RECORD_NOT_FOUND stale-record race (the ``elif
    WarningCode.RECORD_NOT_FOUND.value in result.errors:`` branch in
    ``_on_save``) must set ``record_vanished``, warn the user, and close the
    dialog -- this branch was shipped with zero test coverage."""
    dialog = _make_dialog_for_record_not_found()
    controller_mock = mock.MagicMock()
    dialog._controller = controller_mock
    controller_mock.save_record.return_value = Result(
        ok=False, errors=(WarningCode.RECORD_NOT_FOUND.value,)
    )
    destroy_mock = mock.MagicMock()
    dialog.destroy = destroy_mock

    with mock.patch("views.dialog_common.messagebox") as messagebox_mock:
        dialog._on_save()

    controller_mock.save_record.assert_called_once()
    assert controller_mock.save_record.call_args.args[0].id == 123
    assert dialog.record_vanished is True
    messagebox_mock.showwarning.assert_called_once()
    destroy_mock.assert_called_once()


def test_on_save_feeds_charge_rate_into_saved_record() -> None:
    """The Charge spinbox value must flow into the VacationRecord handed to
    the controller — a half-charged day carries charge_rate=0.5."""
    dialog = _make_dialog_for_record_not_found()
    dialog._var_charge.get.return_value = "0.50"
    controller_mock = mock.MagicMock()
    dialog._controller = controller_mock
    controller_mock.save_record.return_value = Result(ok=True)

    with mock.patch("views.vacation_record_dialog.messagebox"):
        dialog._on_save()

    controller_mock.save_record.assert_called_once()
    saved = controller_mock.save_record.call_args.args[0]
    assert saved.charge_rate == 0.5


def test_on_save_non_numeric_charge_is_reported_as_field_error() -> None:
    """A non-numeric Charge entry must surface as a field error before the
    record is built, and must not reach the controller."""
    dialog = _make_dialog_for_record_not_found()
    dialog._var_charge.get.return_value = "abc"
    controller_mock = mock.MagicMock()
    dialog._controller = controller_mock

    dialog._on_save()

    controller_mock.save_record.assert_not_called()
    dialog._lbl_error.config.assert_called_with(
        text="Charge rate must be a number between 0.0 and 1.0."
    )


def test_on_save_out_of_range_charge_shows_invariant_error() -> None:
    """An in-range-parseable but out-of-bounds Charge (e.g. 1.5) is rejected by
    the VacationRecord invariant, surfaced inline, and never saved."""
    dialog = _make_dialog_for_record_not_found()
    dialog._var_charge.get.return_value = "1.50"
    controller_mock = mock.MagicMock()
    dialog._controller = controller_mock

    dialog._on_save()

    controller_mock.save_record.assert_not_called()
    dialog._lbl_error.config.assert_called_with(
        text="Charge rate must be between 0.0 and 1.0."
    )
