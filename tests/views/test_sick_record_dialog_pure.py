"""Tests for SickRecordDialog._on_save's RECORD_NOT_FOUND handling (no Tk
mainloop needed).

Mirrors the ``__new__``-bypass pattern used in
tests/views/test_vacation_record_dialog_pure.py and
tests/views/test_report_dialog.py: the dialog's Tk widgets are stood in
with MagicMocks so ``_on_save`` can run without a live Tk interpreter or
display, matching this repo's headless-CI constraint (see the module
docstring in tests/views/test_help_viewer_dialogs.py).
"""

from datetime import date
from unittest import mock

from domain.enums import WarningCode
from domain.types import Result
from views.sick_record_dialog import SickRecordDialog


def _make_dialog_for_record_not_found() -> SickRecordDialog:
    """Stand in every widget ``_on_save`` touches on the single-day success
    path, with field values that pass ``SicknessRecord``'s invariants, so
    ``_on_save`` actually reaches ``self._controller.save_record(...)`` and
    the RECORD_NOT_FOUND branch under test can be exercised.

    ``_var_multiday`` is deliberately left unset: ``_on_save`` reads it via
    ``hasattr(self, "_var_multiday")``, which is ``False`` for a
    ``__new__``-bypassed instance, so the single-day (``save_record``)
    branch is taken rather than the multi-day (``save_range``) branch.
    """
    dialog = SickRecordDialog.__new__(SickRecordDialog)
    dialog._get_date = lambda: date(2026, 6, 1)
    dialog._lbl_error = mock.MagicMock()
    dialog._var_hours = mock.MagicMock()
    dialog._var_hours.get.return_value = "8.0"
    dialog._var_note = mock.MagicMock()
    dialog._var_note.get.return_value = ""
    dialog._get_doc_path = lambda: None
    dialog._record = None
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

    assert dialog.record_vanished is True
    messagebox_mock.showwarning.assert_called_once()
    destroy_mock.assert_called_once()
