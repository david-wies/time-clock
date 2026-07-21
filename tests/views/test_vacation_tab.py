"""Regression tests for VacationTab._do_edit()'s no-selection guard (no live
Tk display needed).

This repo's CI runs headless with no X display (see tests/views/
test_help_viewer_dialogs.py and test_report_dialog.py for the same
constraint on other view modules), so VacationTab is built via
``VacationTab.__new__`` (bypassing ``__init__``, which constructs real ttk
widgets) with just the attributes ``_do_edit()`` actually touches --
mirroring the ``_make_tab`` bypass pattern in
tests/views/test_time_clock_tab_dedup.py,
tests/views/test_sickness_tab_dedup.py, and tests/views/test_miliuim_tab.py.
The Treeview is replaced with a lightweight fake exposing only
``selection()``, and ``VacationRecordDialog`` (a ``tk.Toplevel`` subclass
that cannot be built headless) is patched out at the module level it is
imported into.

Before the fix, ``_do_edit()`` fell through to
``self.model.get_record_by_id(None)`` when nothing was selected in the
tree, which returned ``None`` and popped a misleading "Record Not Found"
dialog on a keyboard shortcut press (e.g. Ctrl-E) with no selection --
rather than simply doing nothing, as a no-op edit action should.
"""

from datetime import date
from tkinter import ttk
from typing import cast
from unittest import mock

from core.events import EventBus
from db.database import Database
from domain.enums import VacationType, WarningCode
from domain.types import Hours, Result, VacationRecord
from models.vacation_model import VacationModel
from views.vacation_tab import VacationTab


class _FakeTree:
    """Stand-in for the ttk.Treeview: only ``selection()`` is exercised by
    ``_get_selected_record_id()``, which is all ``_do_edit()`` needs."""

    def __init__(self, selected_iid: str | None = None) -> None:
        self._selected_iid = selected_iid

    def selection(self):
        return (self._selected_iid,) if self._selected_iid is not None else ()


def _make_tab(model: VacationModel, selected_iid: str | None) -> VacationTab:
    """Builds a VacationTab without running __init__ / constructing real Tk
    widgets -- only the attributes touched by ``_do_edit()`` are set."""
    tab = VacationTab.__new__(VacationTab)
    tab.model = model
    tab.controller = mock.Mock()
    tab._tree = cast(ttk.Treeview, _FakeTree(selected_iid))
    return tab


def test_do_edit_with_no_selection_does_not_fetch_or_show_dialog(
    db: Database, event_bus: EventBus
) -> None:
    """With nothing selected in the tree, _do_edit() must return immediately
    -- no get_record_by_id() lookup and no VacationRecordDialog popped."""
    model = VacationModel(db, event_bus)
    tab = _make_tab(model, selected_iid=None)

    with (
        mock.patch.object(
            model, "get_record_by_id", wraps=model.get_record_by_id
        ) as lookup_spy,
        mock.patch("views.vacation_tab.messagebox") as messagebox_mock,
        mock.patch("views.vacation_tab.VacationRecordDialog") as dialog_mock,
    ):
        tab._do_edit()

    lookup_spy.assert_not_called()
    messagebox_mock.showwarning.assert_not_called()
    dialog_mock.assert_not_called()


def test_do_edit_with_valid_selection_opens_edit_dialog(
    db: Database, event_bus: EventBus
) -> None:
    """Regression guard on the happy path: a valid selected record id must
    still fetch the record and open VacationRecordDialog with it, exactly
    as before the no-selection guard was added."""
    model = VacationModel(db, event_bus)
    rec_id = model.insert_record(
        VacationRecord(
            None, date(2026, 6, 1), Hours(8.0), VacationType.ANNUAL_LEAVE, "Trip"
        )
    )
    rec = model.get_record_by_id(rec_id)
    tab = _make_tab(model, selected_iid=f"rec_{rec_id}")

    with (
        mock.patch.object(
            model, "get_record_by_id", wraps=model.get_record_by_id
        ) as lookup_spy,
        mock.patch("views.vacation_tab.messagebox") as messagebox_mock,
        mock.patch("views.vacation_tab.VacationRecordDialog") as dialog_mock,
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
    model = VacationModel(db, event_bus)
    rec_id = model.insert_record(
        VacationRecord(
            None, date(2026, 6, 1), Hours(8.0), VacationType.ANNUAL_LEAVE, "Trip"
        )
    )
    tab = _make_tab(model, selected_iid=f"rec_{rec_id}")
    refresh_mock = mock.Mock()
    tab._refresh = refresh_mock

    with (
        mock.patch("views.vacation_tab.messagebox") as messagebox_mock,
        mock.patch("views.vacation_tab.VacationRecordDialog") as dialog_mock,
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
    model = VacationModel(db, event_bus)
    rec_id = model.insert_record(
        VacationRecord(
            None, date(2026, 6, 1), Hours(8.0), VacationType.ANNUAL_LEAVE, "Trip"
        )
    )
    tab = _make_tab(model, selected_iid=f"rec_{rec_id}")
    tab.controller = mock.Mock()
    tab.controller.delete_record.return_value = Result(
        ok=False, errors=(WarningCode.RECORD_NOT_FOUND.value,)
    )
    refresh_mock = mock.Mock()
    tab._refresh = refresh_mock

    with (
        mock.patch("views.vacation_tab.messagebox") as messagebox_mock,
        mock.patch("views.record_tab_common.messagebox") as common_mb,
    ):
        messagebox_mock.askyesno.return_value = True
        tab._do_delete()

    common_mb.showinfo.assert_called_once()
    common_mb.showerror.assert_not_called()
    refresh_mock.assert_called_once()


def test_make_row_values_includes_charged_column() -> None:
    """Each record row exposes both raw hours (col 3) and charge-weighted
    hours (col 4); a half-charged 8h day charges 4h."""
    tab = VacationTab.__new__(VacationTab)
    rec = VacationRecord(
        1, date(2026, 6, 1), Hours(8.0), VacationType.ANNUAL_LEAVE, "Trip", 0.5
    )

    values = tab._make_row_values(rec)

    assert len(values) == 6
    assert values[3] == "8.0h"  # raw hours
    assert values[4] == "4.0h"  # charged (8.0 * 0.5)


def test_make_row_values_none_row_has_six_columns() -> None:
    """The placeholder/total row must match the 6-column tree layout so the
    charged column lines up."""
    tab = VacationTab.__new__(VacationTab)

    values = tab._make_row_values(None, "Total: 8.0h")

    assert values == ("Total: 8.0h", "", "", "", "", "")


def test_borrow_breakdown_parts_empty_without_cap() -> None:
    """With no borrow cap configured, the breakdown adds no borrow fragments
    (pre-#47 layout preserved)."""
    tab = VacationTab.__new__(VacationTab)
    tab.model = mock.Mock()
    tab.model.get_max_borrow_hours.return_value = 0.0

    assert tab._borrow_breakdown_parts(used=10.0, total_pool=8.0) == []


def test_borrow_breakdown_parts_reports_borrowed_and_headroom() -> None:
    """current-year borrowed = max(0, min(used - total_pool, max_borrow));
    headroom = max_borrow - borrowed."""
    tab = VacationTab.__new__(VacationTab)
    tab.model = mock.Mock()
    tab.model.get_max_borrow_hours.return_value = 40.0

    parts = tab._borrow_breakdown_parts(used=50.0, total_pool=40.0)

    assert parts == ["borrowed this yr: 10.0h", "borrow headroom: 30.0h"]


def test_do_grants_opens_grant_dialog(db: Database, event_bus: EventBus) -> None:
    """The Grants… button opens VacationGrantDialog for the selected year,
    wired with the tab's controller/model (mirroring the carry-over button)."""
    model = VacationModel(db, event_bus)
    tab = _make_tab(model, selected_iid=None)
    tab._selected_year = 2026

    with mock.patch("views.vacation_tab.VacationGrantDialog") as dialog_mock:
        tab._do_grants()

    dialog_mock.assert_called_once_with(
        tab, controller=tab.controller, model=model, year=2026
    )
