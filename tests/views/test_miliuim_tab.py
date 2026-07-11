"""Regression tests for MiliuimTab._do_edit()'s no-selection guard (no live
Tk display needed).

This repo's CI runs headless with no X display (see tests/views/
test_help_viewer_dialogs.py and test_report_dialog.py for the same
constraint on other view modules), so MiliuimTab is built via
``MiliuimTab.__new__`` (bypassing ``__init__``, which constructs real ttk
widgets) with just the attributes ``_do_edit()`` actually touches --
mirroring the ``_make_tab`` bypass pattern in
tests/views/test_time_clock_tab_dedup.py and
tests/views/test_sickness_tab_dedup.py. The Treeview is replaced with a
lightweight fake exposing only ``selection()``, and
``MiliuimRecordDialog`` (a ``tk.Toplevel`` subclass that cannot be built
headless) is patched out at the module level it is imported into.

Before the fix, ``_do_edit()`` fell through to
``self.model.get_record_by_id(None)`` when nothing was selected in the
tree, which returned ``None`` and popped a misleading "Record Not Found"
dialog on a keyboard shortcut press with no selection -- rather than
simply doing nothing, as a no-op edit action should.
"""

from datetime import date
from unittest import mock

from core.events import EventBus
from db.database import Database
from domain.types import MiliuimRecord
from models.miliuim_model import MiliuimModel
from views.miliuim_tab import MiliuimTab


class _FakeTree:
    """Stand-in for the ttk.Treeview: only ``selection()`` is exercised by
    ``_get_selected_record_id()``, which is all ``_do_edit()`` needs."""

    def __init__(self, selected_iid: str | None = None) -> None:
        self._selected_iid = selected_iid

    def selection(self):
        return (self._selected_iid,) if self._selected_iid is not None else ()


def _make_tab(model: MiliuimModel, selected_iid: str | None) -> MiliuimTab:
    """Builds a MiliuimTab without running __init__ / constructing real Tk
    widgets -- only the attributes touched by ``_do_edit()`` are set."""
    tab = MiliuimTab.__new__(MiliuimTab)
    tab.model = model
    tab.controller = mock.Mock()
    tab._tree = _FakeTree(selected_iid)
    return tab


def test_do_edit_with_no_selection_does_not_fetch_or_show_dialog(
    db: Database, event_bus: EventBus
) -> None:
    """With nothing selected in the tree, _do_edit() must return immediately
    -- no get_record_by_id() lookup and no MiliuimRecordDialog popped."""
    model = MiliuimModel(db, event_bus)
    tab = _make_tab(model, selected_iid=None)

    with (
        mock.patch.object(
            model, "get_record_by_id", wraps=model.get_record_by_id
        ) as lookup_spy,
        mock.patch("views.miliuim_tab.messagebox") as messagebox_mock,
        mock.patch("views.miliuim_tab.MiliuimRecordDialog") as dialog_mock,
    ):
        tab._do_edit()

    lookup_spy.assert_not_called()
    messagebox_mock.showwarning.assert_not_called()
    dialog_mock.assert_not_called()


def test_do_edit_with_valid_selection_opens_edit_dialog(
    db: Database, event_bus: EventBus
) -> None:
    """Regression guard on the happy path: a valid selected record id must
    still fetch the record and open MiliuimRecordDialog with it, exactly as
    before the no-selection guard was added."""
    model = MiliuimModel(db, event_bus)
    rec_id = model.insert_record(
        MiliuimRecord(None, date(2026, 6, 1), date(2026, 6, 5), "Annual training")
    )
    rec = model.get_record_by_id(rec_id)
    tab = _make_tab(model, selected_iid=f"rec_{rec_id}")

    with (
        mock.patch.object(
            model, "get_record_by_id", wraps=model.get_record_by_id
        ) as lookup_spy,
        mock.patch("views.miliuim_tab.messagebox") as messagebox_mock,
        mock.patch("views.miliuim_tab.MiliuimRecordDialog") as dialog_mock,
    ):
        # The real dialog sets record_vanished=False unless its save hit
        # the RECORD_NOT_FOUND stale-record race; a bare MagicMock
        # attribute is truthy and would wrongly trigger the tab's
        # post-dialog refresh path.
        dialog_mock.return_value.record_vanished = False
        tab._do_edit()

    lookup_spy.assert_called_once_with(rec_id)
    messagebox_mock.showwarning.assert_not_called()
    dialog_mock.assert_called_once_with(
        tab, controller=tab.controller, model=model, record=rec
    )
