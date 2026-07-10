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
