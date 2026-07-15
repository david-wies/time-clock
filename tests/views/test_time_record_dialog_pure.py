"""Tests for TimeRecordDialog._on_save's RECORD_NOT_FOUND handling (no Tk
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

from domain.enums import WarningCode, WorkType
from domain.types import Result
from views.time_record_dialog import TimeRecordDialog


def _make_dialog_for_record_not_found() -> TimeRecordDialog:
    """Stand in every widget ``_on_save`` touches on the full success path,
    with field values that pass ``TimeRecord``'s invariants, so ``_on_save``
    actually reaches ``self._controller.save_record(...)`` and the
    RECORD_NOT_FOUND branch under test can be exercised.

    Work type is ``REMOTE`` deliberately: it is the only ``WorkType`` that
    needs neither an office (``IN_SITE``-only requirement) nor a document
    path (``ROAD``-only branch), so ``_var_office``/``_get_doc_path`` never
    need to be stood in.

    ``_record`` is an existing record with a non-null id (not ``None``):
    RECORD_NOT_FOUND is a stale-*edit* race — a zero-row update — so the
    branch is only reachable on the update path, and the surviving id must
    reach ``save_record``.
    """
    dialog = TimeRecordDialog.__new__(TimeRecordDialog)
    dialog._get_date = lambda: date(2026, 6, 1)
    dialog._lbl_error = mock.MagicMock()
    dialog._var_start = mock.MagicMock()
    dialog._var_start.get.return_value = "09:00"
    dialog._var_end = mock.MagicMock()
    dialog._var_end.get.return_value = "17:00"
    dialog._var_break = mock.MagicMock()
    dialog._var_break.get.return_value = "00:00"
    dialog._var_work_type = mock.MagicMock()
    dialog._var_work_type.get.return_value = str(WorkType.REMOTE)
    dialog._var_note = mock.MagicMock()
    dialog._var_note.get.return_value = ""
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
