"""Tests for ExportDialog._on_export's partial-file-on-failure handling.

Builds the dialog via ``ExportDialog.__new__`` (bypassing Tk's __init__ /
wait_window) so this runs without a live Tk interpreter, matching the
headless-CI constraint documented in tests/views/test_report_dialog.py and
tests/views/test_help_viewer_dialogs.py. ``tkinter.filedialog`` /
``tkinter.messagebox`` are monkeypatched module-level so no real dialog
windows are created.
"""

import os
from datetime import date
from unittest import mock

import pytest

from models.sickness_model import SicknessModel
from models.time_clock_model import TimeClockModel
from models.vacation_model import VacationModel
from views.export_dialog import ExportDialog


def _make_dialog(fmt: str = "csv") -> ExportDialog:
    dialog = ExportDialog.__new__(ExportDialog)
    dialog._var_fmt = mock.MagicMock(get=mock.MagicMock(return_value=fmt))
    dialog._var_data = mock.MagicMock(get=mock.MagicMock(return_value="time"))
    dialog._var_group = mock.MagicMock(get=mock.MagicMock(return_value=True))
    dialog._get_from = lambda: date(2026, 1, 1)
    dialog._get_to = lambda: date(2026, 12, 31)
    dialog.destroy = mock.MagicMock()
    return dialog


def test_export_failure_leaves_no_partial_file_at_final_path(
    tmp_path, monkeypatch
) -> None:
    """A mid-export exception must not leave a truncated file at the
    user-chosen path — the old behaviour wrote incrementally to `path`
    directly and left whatever had been written so far in place."""
    dialog = _make_dialog()
    final_path = str(tmp_path / "export.csv")

    monkeypatch.setattr(
        "views.export_dialog.filedialog.asksaveasfilename",
        lambda **_kw: final_path,
    )
    show_error = mock.MagicMock()
    show_info = mock.MagicMock()
    monkeypatch.setattr("views.export_dialog.messagebox.showerror", show_error)
    monkeypatch.setattr("views.export_dialog.messagebox.showinfo", show_info)
    monkeypatch.setattr(dialog, "_fetch_records", lambda *_a: ([], 0))

    def _boom(_records, path: str) -> None:
        # Simulate a real writer that gets partway through before failing.
        with open(path, "w", encoding="utf-8") as f:
            f.write("Date,Hours\n2026-01-01,")
        raise RuntimeError("disk full")

    monkeypatch.setattr(dialog, "_export_csv", _boom)

    dialog._on_export()

    assert not os.path.exists(final_path), (
        "a partial file must not be left at the final export path"
    )
    assert not os.path.exists(final_path + ".tmp"), (
        "the temp file used for the failed write must be cleaned up"
    )
    show_error.assert_called_once()
    show_info.assert_not_called()
    dialog.destroy.assert_not_called()


def test_export_success_writes_final_path_and_leaves_no_temp_file(
    tmp_path, monkeypatch
) -> None:
    dialog = _make_dialog()
    final_path = str(tmp_path / "export.csv")

    monkeypatch.setattr(
        "views.export_dialog.filedialog.asksaveasfilename",
        lambda **_kw: final_path,
    )
    show_error = mock.MagicMock()
    show_info = mock.MagicMock()
    show_warning = mock.MagicMock()
    monkeypatch.setattr("views.export_dialog.messagebox.showerror", show_error)
    monkeypatch.setattr("views.export_dialog.messagebox.showinfo", show_info)
    monkeypatch.setattr("views.export_dialog.messagebox.showwarning", show_warning)
    monkeypatch.setattr(dialog, "_fetch_records", lambda *_a: ([], 0))

    def _write(_records, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            f.write("Date,Hours\n2026-01-01,8.0\n")

    monkeypatch.setattr(dialog, "_export_csv", _write)

    dialog._on_export()

    assert os.path.exists(final_path)
    assert not os.path.exists(final_path + ".tmp")
    with open(final_path, encoding="utf-8") as f:
        assert f.read() == "Date,Hours\n2026-01-01,8.0\n"
    show_error.assert_not_called()
    show_info.assert_called_once()
    show_warning.assert_not_called()
    dialog.destroy.assert_called_once()


def test_export_with_skipped_records_shows_warning_not_info(
    tmp_path, monkeypatch
) -> None:
    """When the underlying model fetch silently dropped malformed rows, the
    export must still succeed (the row is malformed, not the export), but
    the completion dialog must warn the user rather than silently claiming
    success -- otherwise a partial-but-complete-looking export is exactly
    the failure mode the temp-file/rename dance in `_on_export()` exists to
    prevent (see the comment at the top of that method)."""
    dialog = _make_dialog()
    final_path = str(tmp_path / "export.csv")

    monkeypatch.setattr(
        "views.export_dialog.filedialog.asksaveasfilename",
        lambda **_kw: final_path,
    )
    show_error = mock.MagicMock()
    show_info = mock.MagicMock()
    show_warning = mock.MagicMock()
    monkeypatch.setattr("views.export_dialog.messagebox.showerror", show_error)
    monkeypatch.setattr("views.export_dialog.messagebox.showinfo", show_info)
    monkeypatch.setattr("views.export_dialog.messagebox.showwarning", show_warning)
    monkeypatch.setattr(dialog, "_fetch_records", lambda *_a: ([], 3))

    def _write(_records, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            f.write("Date,Hours\n2026-01-01,8.0\n")

    monkeypatch.setattr(dialog, "_export_csv", _write)

    dialog._on_export()

    assert os.path.exists(final_path)
    show_error.assert_not_called()
    show_info.assert_not_called()
    show_warning.assert_called_once()
    warning_text = show_warning.call_args.args[1]
    assert "3 record(s) skipped due to data errors" in warning_text
    dialog.destroy.assert_called_once()


def test_export_invalid_date_range_shows_error_before_touching_filesystem(
    monkeypatch,
) -> None:
    dialog = _make_dialog()
    dialog._get_from = lambda: date(2026, 12, 31)
    dialog._get_to = lambda: date(2026, 1, 1)  # to < from

    show_error = mock.MagicMock()
    monkeypatch.setattr("views.export_dialog.messagebox.showerror", show_error)
    asksave = mock.MagicMock()
    monkeypatch.setattr("views.export_dialog.filedialog.asksaveasfilename", asksave)

    dialog._on_export()

    show_error.assert_called_once()
    asksave.assert_not_called()


# ─────────── Real _fetch_records: multi-year skip-count accumulation ──────────
#
# The tests above monkeypatch `_fetch_records` wholesale, so the real
# per-year / per-tab body (which sums `year_skipped` across
# `from_date.year..to_date.year`) never runs. The tests below drive the
# genuine method against real models backed by the in-memory `db` fixture,
# proving both years of a two-year range are summed rather than only the last.


@pytest.fixture
def export_models(db, event_bus):
    """Real (time, vacation, sickness) models sharing one in-memory DB.

    Wired into an ``ExportDialog`` built via ``__new__`` so the production
    ``_fetch_records`` executes end-to-end without a live Tk interpreter.
    """
    return (
        TimeClockModel(db, event_bus),
        VacationModel(db, event_bus),
        SicknessModel(db, event_bus),
    )


def _make_fetch_dialog(export_models, tab: str) -> ExportDialog:
    """Build a headless dialog wired to the real models with `tab` selected."""
    model_tc, model_vacation, model_sickness = export_models
    dialog = ExportDialog.__new__(ExportDialog)
    dialog._model_tc = model_tc
    dialog._model_vacation = model_vacation
    dialog._model_sickness = model_sickness
    dialog._var_data = mock.MagicMock(get=mock.MagicMock(return_value=tab))
    return dialog


def _exec(db, sql: str, params: tuple = ()) -> None:
    """Run one raw INSERT via a short-lived connection.

    Malformed rows are inserted with raw SQL so they bypass the model-layer
    validation that would otherwise reject them (matching the technique in
    tests/core/test_report.py). On fetch, the model silently drops such rows
    and bumps its ``last_skipped_count``, which `_fetch_records` accumulates.
    """
    conn = db.get_connection()
    try:
        with conn:
            conn.execute(sql, params)
    finally:
        conn.close()


_BAD_TIME_SQL = (
    "INSERT INTO time_record "
    "(date, start_time, end_time, break_minutes, work_type) "
    "VALUES (?, '09:00', '10:00', 600, 'remote');"  # break > shift → invalid
)
_GOOD_TIME_SQL = (
    "INSERT INTO time_record "
    "(date, start_time, end_time, break_minutes, work_type) "
    "VALUES (?, '09:00', '17:00', 30, 'remote');"
)
_BAD_VAC_SQL = (
    "INSERT INTO vacation_record (date, hours, vtype, note) "
    "VALUES (?, 4.0, 'annual_leave', ?);"  # note param overflows 500-char limit
)
_GOOD_VAC_SQL = (
    "INSERT INTO vacation_record (date, hours, vtype, note) "
    "VALUES (?, 4.0, 'annual_leave', '');"
)


def test_fetch_records_time_sums_skipped_across_two_years(export_models, db) -> None:
    """A malformed time_record in EACH of two years must make
    `_fetch_records` return `skipped_count == 2`.

    This is the regression the whole test file otherwise misses: a bug that
    reset `year_skipped` in the wrong place, or that returned only the last
    year's skip count, would still yield 1 here (or 0) instead of 2. A good
    row per year is inserted too, so the returned record list also proves
    both years were actually fetched.
    """
    dialog = _make_fetch_dialog(export_models, "time")
    _exec(db, _BAD_TIME_SQL, ("2025-03-15",))
    _exec(db, _BAD_TIME_SQL, ("2026-03-15",))
    _exec(db, _GOOD_TIME_SQL, ("2025-06-01",))
    _exec(db, _GOOD_TIME_SQL, ("2026-06-01",))

    records, skipped_count = dialog._fetch_records(date(2025, 1, 1), date(2026, 12, 31))

    assert skipped_count == 2, "both years' skip counts must be summed, not just one"
    assert [r.date for r in records] == [date(2025, 6, 1), date(2026, 6, 1)]


def test_fetch_records_vacation_sums_skipped_across_two_years(
    export_models, db
) -> None:
    """Same two-year accumulation contract for the VACATION tab: one
    malformed vacation row per year must sum to `skipped_count == 2`,
    confirming the per-tab wiring routes through the vacation model's own
    `last_skipped_count` for every year in the range."""
    dialog = _make_fetch_dialog(export_models, "vacation")
    long_note = "x" * 501
    _exec(db, _BAD_VAC_SQL, ("2025-04-10", long_note))
    _exec(db, _BAD_VAC_SQL, ("2026-04-10", long_note))
    _exec(db, _GOOD_VAC_SQL, ("2025-07-01",))
    _exec(db, _GOOD_VAC_SQL, ("2026-07-01",))

    records, skipped_count = dialog._fetch_records(date(2025, 1, 1), date(2026, 12, 31))

    assert skipped_count == 2, "both years' skip counts must be summed, not just one"
    assert [r.date for r in records] == [date(2025, 7, 1), date(2026, 7, 1)]
