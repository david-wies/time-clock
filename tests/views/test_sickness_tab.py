"""Regression tests for SicknessTab's RECORD_NOT_FOUND stale-record-race
handling in ``_do_edit()``/``_do_delete()`` (no live Tk display needed).

This repo's CI runs headless with no X display (see tests/views/
test_help_viewer_dialogs.py and test_report_dialog.py for the same
constraint on other view modules), so SicknessTab is built via
``SicknessTab.__new__`` (bypassing ``__init__``, which constructs real ttk
widgets) with just the attributes ``_do_edit()``/``_do_delete()`` actually
touch -- mirroring the ``_make_tab`` bypass pattern in
tests/views/test_miliuim_tab.py, whose ``_do_edit()``/``_do_delete()``
bodies are structurally identical to SicknessTab's (both delegate to the
shared ``RecordTabMixin._get_selected_record_id()`` and share the same
RECORD_NOT_FOUND branch shape). The Treeview is replaced with a
lightweight fake exposing only ``selection()``, and ``SickRecordDialog``
(a ``tk.Toplevel`` subclass that cannot be built headless) is patched out
at the module level it is imported into.
"""

from datetime import date
from unittest import mock

from core.events import EventBus
from db.database import Database
from domain.enums import WarningCode
from domain.types import Hours, Result, SicknessRecord
from models.sickness_model import SicknessModel
from views.sickness_tab import SicknessTab


class _FakeTree:
    """Stand-in for the ttk.Treeview: only ``selection()`` is exercised by
    ``_get_selected_record_id()``, which is all ``_do_edit()``/``_do_delete()``
    need."""

    def __init__(self, selected_iid: str | None = None) -> None:
        self._selected_iid = selected_iid

    def selection(self):
        return (self._selected_iid,) if self._selected_iid is not None else ()


def _make_tab(model: SicknessModel, selected_iid: str | None) -> SicknessTab:
    """Builds a SicknessTab without running __init__ / constructing real Tk
    widgets -- only the attributes touched by ``_do_edit()``/``_do_delete()``
    are set."""
    tab = SicknessTab.__new__(SicknessTab)
    tab.model = model
    tab.controller = mock.Mock()
    tab._tree = _FakeTree(selected_iid)
    return tab


def test_do_edit_with_no_selection_does_not_fetch_or_show_dialog(
    db: Database, event_bus: EventBus
) -> None:
    """With nothing selected in the tree, _do_edit() must return immediately
    -- no get_record_by_id() lookup and no SickRecordDialog popped."""
    model = SicknessModel(db, event_bus)
    tab = _make_tab(model, selected_iid=None)

    with (
        mock.patch.object(
            model, "get_record_by_id", wraps=model.get_record_by_id
        ) as lookup_spy,
        mock.patch("views.sickness_tab.messagebox") as messagebox_mock,
        mock.patch("views.sickness_tab.SickRecordDialog") as dialog_mock,
    ):
        tab._do_edit()

    lookup_spy.assert_not_called()
    messagebox_mock.showwarning.assert_not_called()
    dialog_mock.assert_not_called()


def test_do_edit_with_valid_selection_opens_edit_dialog(
    db: Database, event_bus: EventBus
) -> None:
    """Regression guard on the happy path: a valid selected record id must
    still fetch the record and open SickRecordDialog with it, exactly as
    before the no-selection guard was added."""
    model = SicknessModel(db, event_bus)
    rec_id = model.insert_record(
        SicknessRecord(None, date(2026, 6, 22), Hours(8.0), "Flu")
    )
    rec = model.get_record_by_id(rec_id)
    tab = _make_tab(model, selected_iid=f"rec_{rec_id}")

    with (
        mock.patch.object(
            model, "get_record_by_id", wraps=model.get_record_by_id
        ) as lookup_spy,
        mock.patch("views.sickness_tab.messagebox") as messagebox_mock,
        mock.patch("views.sickness_tab.SickRecordDialog") as dialog_mock,
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


def test_do_edit_record_vanished_true_triggers_refresh(
    db: Database, event_bus: EventBus
) -> None:
    """The other half of the ``dlg.record_vanished`` branch in ``_do_edit()``
    -- when the modal dialog's save hit the RECORD_NOT_FOUND stale-record
    race, ``record_vanished`` comes back ``True`` and ``_do_edit()`` must
    call ``self._refresh()`` to clear the now-phantom row. Only the
    ``False`` (no-op) half of this branch had coverage before."""
    model = SicknessModel(db, event_bus)
    rec_id = model.insert_record(
        SicknessRecord(None, date(2026, 6, 22), Hours(8.0), "Flu")
    )
    tab = _make_tab(model, selected_iid=f"rec_{rec_id}")
    refresh_mock = mock.Mock()
    tab._refresh = refresh_mock

    with (
        mock.patch("views.sickness_tab.messagebox") as messagebox_mock,
        mock.patch("views.sickness_tab.SickRecordDialog") as dialog_mock,
    ):
        dialog_mock.return_value.record_vanished = True
        tab._do_edit()

    messagebox_mock.showwarning.assert_not_called()
    refresh_mock.assert_called_once()


def test_do_delete_record_not_found_shows_info_and_refreshes(
    db: Database, event_bus: EventBus
) -> None:
    """``_do_delete()``'s RECORD_NOT_FOUND branch (the stale-record race
    where the row was already removed elsewhere) must show the friendly
    "Record Already Removed" info box -- not the generic error box -- and
    call ``self._refresh()`` to clear the phantom row."""
    model = SicknessModel(db, event_bus)
    rec_id = model.insert_record(
        SicknessRecord(None, date(2026, 6, 22), Hours(8.0), "Flu")
    )
    tab = _make_tab(model, selected_iid=f"rec_{rec_id}")
    tab.controller = mock.Mock()
    tab.controller.delete_record.return_value = Result(
        ok=False, errors=(WarningCode.RECORD_NOT_FOUND.value,)
    )
    refresh_mock = mock.Mock()
    tab._refresh = refresh_mock

    with mock.patch("views.sickness_tab.messagebox") as messagebox_mock:
        messagebox_mock.askyesno.return_value = True
        tab._do_delete()

    messagebox_mock.showinfo.assert_called_once()
    messagebox_mock.showerror.assert_not_called()
    refresh_mock.assert_called_once()
