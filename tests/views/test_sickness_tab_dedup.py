"""Regression test for the SicknessTab / SicknessModel duplicate year-records
fetch fix (no live Tk display needed).

This repo's CI runs headless with no X display (see tests/views/
test_help_viewer_dialogs.py and test_report_dialog.py for the same
constraint on other view modules), so SicknessTab is built via
``SicknessTab.__new__`` (bypassing ``__init__``, which constructs real
ttk widgets) with just the attributes ``_refresh()`` actually touches --
mirroring the ``_make_dialog`` bypass pattern in
tests/views/test_report_dialog.py. Tree/label/button widgets are replaced
with lightweight fakes exposing only the methods the tab calls on them.
"""

from datetime import date
from tkinter import ttk
from typing import cast
from unittest import mock

from core.events import EventBus
from db.database import Database
from domain.types import Hours, SicknessRecord
from models.sickness_model import SicknessModel
from views.sickness_tab import SicknessTab


class _FakeWidget:
    """Stand-in for a ttk.Label/Button: records config() calls, does nothing."""

    def config(self, **_kw) -> None:
        pass


class _FakeTree:
    """Stand-in for the ttk.Treeview: tracks inserted rows, no real widget."""

    def __init__(self) -> None:
        self._rows: list[tuple] = []

    def get_children(self):
        return tuple(range(len(self._rows)))

    def delete(self, *_iids) -> None:
        self._rows.clear()

    def insert(self, _parent, _pos, iid=None, values=(), tags=()) -> str:
        self._rows.append(values)
        return iid or f"row_{len(self._rows)}"

    def tag_configure(self, *_a, **_kw) -> None:
        pass

    def selection(self):
        return ()


def _make_tab(model: SicknessModel, year: int, month: int) -> SicknessTab:
    """Builds a SicknessTab without running __init__ / constructing real
    Tk widgets -- only the attributes touched by _refresh() are set."""
    tab = SicknessTab.__new__(SicknessTab)
    tab.model = model
    tab._theme_mode = "light"
    tab._selected_year = year
    tab._selected_month = month
    tab._tree = cast(ttk.Treeview, _FakeTree())
    tab._lbl_balance = cast(ttk.Label, _FakeWidget())
    tab._lbl_hours = cast(ttk.Label, _FakeWidget())
    tab._btn_edit = cast(ttk.Button, _FakeWidget())
    tab._btn_delete = cast(ttk.Button, _FakeWidget())
    return tab


def test_refresh_fetches_year_records_only_once(
    db: Database, event_bus: EventBus
) -> None:
    """_refresh() must call get_records_for_year() exactly once per cycle
    and reuse the same list for both the balance summary and the tree --
    previously calculate_sickness_summary() and _refresh_tree() each
    queried the DB independently for the identical full-year record set
    whenever the month filter was 'All'."""
    model = SicknessModel(db, event_bus)
    model.save_settings(2026, 80.0)
    model.insert_record(SicknessRecord(None, date(2026, 6, 22), Hours(8.0), "Flu"))
    model.insert_record(SicknessRecord(None, date(2026, 3, 1), Hours(4.0), "Cold"))

    tab = _make_tab(model, year=2026, month=0)  # 0 = "All" months

    with mock.patch.object(
        model, "get_records_for_year", wraps=model.get_records_for_year
    ) as spy:
        tab._refresh()
        assert spy.call_count == 1


def test_refresh_fetches_once_even_with_specific_month_selected(
    db: Database, event_bus: EventBus
) -> None:
    """Even when a specific month is selected (not 'All'), the balance
    summary still needs the full year's records -- _refresh() must still
    only hit the DB once and filter the month client-side for the tree,
    not issue a second query."""
    model = SicknessModel(db, event_bus)
    model.save_settings(2026, 80.0)
    model.insert_record(SicknessRecord(None, date(2026, 6, 22), Hours(8.0), "Flu"))
    model.insert_record(SicknessRecord(None, date(2026, 3, 1), Hours(4.0), "Cold"))

    tab = _make_tab(model, year=2026, month=6)

    with mock.patch.object(
        model, "get_records_for_year", wraps=model.get_records_for_year
    ) as spy:
        tab._refresh()
        assert spy.call_count == 1

    # And the tree only shows the June record (client-side month filter).
    rows = cast(_FakeTree, tab._tree)._rows
    assert len(rows) == 2  # June record row + "Total" row
    assert rows[0][2] == "8.0h"


def test_refresh_tree_shows_all_records_when_month_is_all(
    db: Database, event_bus: EventBus
) -> None:
    model = SicknessModel(db, event_bus)
    model.save_settings(2026, 80.0)
    model.insert_record(SicknessRecord(None, date(2026, 6, 22), Hours(8.0), "Flu"))
    model.insert_record(SicknessRecord(None, date(2026, 3, 1), Hours(4.0), "Cold"))

    tab = _make_tab(model, year=2026, month=0)
    tab._refresh()

    # Both records + the "Total" row.
    assert len(cast(_FakeTree, tab._tree)._rows) == 3
