"""Regression tests for the TimeClockTab duplicate targets/exceptions fetch
fix (no live Tk display needed).

This repo's CI runs headless with no X display (see tests/views/
test_help_viewer_dialogs.py and test_report_dialog.py for the same
constraint on other view modules), so TimeClockTab is built via
``TimeClockTab.__new__`` (bypassing ``__init__``, which constructs real
ttk widgets) with just the attributes the refresh methods actually touch
-- mirroring the ``_make_dialog`` bypass pattern in
tests/views/test_report_dialog.py. Tree/label/button widgets are replaced
with lightweight fakes exposing only the methods the tab calls on them.

Before the fix: ``_refresh_header()`` and ``_populate_month()``/
``_populate_week()`` each independently called
``model.get_work_day_targets()`` and ``model.get_date_exceptions(year)``,
so every ``_refresh()`` (and every 60s ``_auto_refresh()`` tick while
clocked in) queried the DB twice for the same data. The fix threads a
single ``targets`` fetch and a per-year exceptions cache through
``_refresh_header``/``_populate_month``/``_populate_week``, built once per
refresh cycle in ``_refresh()``/``_auto_refresh()``.
"""

from datetime import date, time, timedelta
from tkinter import Misc, ttk
from typing import cast
from unittest import mock

from core.events import EventBus
from db.database import Database
from domain.enums import WorkType
from domain.types import TimeRecord
from models.time_clock_model import TimeClockModel
from settings import SettingsManager
from views.time_clock_tab import TimeClockTab


class _FakeWidget:
    def config(self, **_kw) -> None:
        pass


class _CaptureLabel:
    """Label fake that records its text so _append_skip_notice()'s
    cget/config round-trip can be observed."""

    def __init__(self) -> None:
        self.text = ""

    def config(self, **kw) -> None:
        if "text" in kw:
            self.text = kw["text"]

    def cget(self, key: str) -> str:
        return self.text if key == "text" else ""


class _FakeTree:
    def __init__(self) -> None:
        self._rows: list[tuple] = []

    def get_children(self):
        return tuple(range(len(self._rows)))

    def delete(self, *_iids) -> None:
        self._rows.clear()

    def insert(
        self, _parent, _pos, text="", iid=None, values=(), tags=(), open=None
    ) -> str:
        self._rows.append((text, values))
        return iid or f"row_{len(self._rows)}"

    def selection(self):
        return ()


def _make_tab(
    model: TimeClockModel,
    settings: SettingsManager,
    view_mode: str,
    selected_year: int,
    selected_month: int,
    selected_week_start: date,
) -> TimeClockTab:
    """Builds a TimeClockTab without running __init__ / constructing real
    Tk widgets -- only the attributes touched by the refresh methods are set."""
    tab = TimeClockTab.__new__(TimeClockTab)
    tab.model = model
    tab.settings = settings
    tab._theme_mode = "light"
    tab._view_mode = view_mode
    tab._selected_year = selected_year
    tab._selected_month = selected_month
    tab._selected_week_start = selected_week_start
    tab._after_id = None
    tab._tree = cast(ttk.Treeview, _FakeTree())
    tab._lbl_today = cast(ttk.Label, _FakeWidget())
    tab._lbl_target = cast(ttk.Label, _FakeWidget())
    tab._lbl_remaining = cast(ttk.Label, _FakeWidget())
    tab._btn_clock_in = cast(ttk.Button, _FakeWidget())
    tab._btn_clock_out = cast(ttk.Button, _FakeWidget())
    tab._btn_edit = cast(ttk.Button, _FakeWidget())
    tab._btn_delete = cast(ttk.Button, _FakeWidget())
    return tab


def _spies(model: TimeClockModel):
    return (
        mock.patch.object(
            model, "get_work_day_targets", wraps=model.get_work_day_targets
        ),
        mock.patch.object(
            model, "get_date_exceptions", wraps=model.get_date_exceptions
        ),
    )


def test_refresh_fetches_targets_and_exceptions_once_when_same_year(
    db: Database, event_bus: EventBus, settings_manager: SettingsManager
) -> None:
    """When the viewed month/year matches "today"'s year (the common
    case), _refresh() must fetch targets once and exceptions once total
    across _refresh_header() + _refresh_tree() -- not once per method."""
    model = TimeClockModel(db, event_bus)
    today = date.today()
    tab = _make_tab(
        model,
        settings_manager,
        view_mode="month",
        selected_year=today.year,
        selected_month=today.month,
        selected_week_start=today,
    )

    targets_patch, exc_patch = _spies(model)
    with targets_patch as targets_spy, exc_patch as exc_spy:
        tab._refresh()

    assert targets_spy.call_count == 1
    assert exc_spy.call_count == 1


def test_refresh_fetches_exceptions_once_per_distinct_year(
    db: Database, event_bus: EventBus, settings_manager: SettingsManager
) -> None:
    """When viewing a month/year different from "today"'s real year (e.g.
    browsing an old month while the header still shows real "today"), the
    header needs today's-year exceptions and the tree needs the viewed
    year's exceptions -- two distinct years, so exactly 2 calls (one per
    distinct year), never more (no re-fetching the same year twice)."""
    model = TimeClockModel(db, event_bus)
    today = date.today()
    other_year = today.year - 1
    tab = _make_tab(
        model,
        settings_manager,
        view_mode="month",
        selected_year=other_year,
        selected_month=6,
        selected_week_start=today,
    )

    targets_patch, exc_patch = _spies(model)
    with targets_patch as targets_spy, exc_patch as exc_spy:
        tab._refresh()

    assert targets_spy.call_count == 1
    assert exc_spy.call_count == 2
    called_years = sorted(c.args[0] for c in exc_spy.call_args_list)
    assert called_years == sorted([today.year, other_year])


def test_refresh_week_mode_fetches_once_when_same_year(
    db: Database, event_bus: EventBus, settings_manager: SettingsManager
) -> None:
    model = TimeClockModel(db, event_bus)
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    tab = _make_tab(
        model,
        settings_manager,
        view_mode="week",
        selected_year=today.year,
        selected_month=today.month,
        selected_week_start=week_start,
    )

    targets_patch, exc_patch = _spies(model)
    with targets_patch as targets_spy, exc_patch as exc_spy:
        tab._refresh()

    assert targets_spy.call_count == 1
    assert exc_spy.call_count == 1


def test_auto_refresh_fetches_targets_and_exceptions_once(
    db: Database, event_bus: EventBus, settings_manager: SettingsManager
) -> None:
    """_auto_refresh() (the 60s timer while clocked in) calls
    _refresh_header() then _refresh_tree() back-to-back -- same
    double-fetch shape as _refresh(), must be deduped identically."""
    model = TimeClockModel(db, event_bus)
    today = date.today()
    tab = _make_tab(
        model,
        settings_manager,
        view_mode="month",
        selected_year=today.year,
        selected_month=today.month,
        selected_week_start=today,
    )

    class _FakeRoot:
        def after(self, *_a, **_kw):
            return "after_id"

    tab.root = cast(Misc, _FakeRoot())

    targets_patch, exc_patch = _spies(model)
    with targets_patch as targets_spy, exc_patch as exc_spy:
        tab._auto_refresh()

    # No open records in an empty DB -> _auto_refresh() short-circuits and
    # does not refresh at all.
    assert targets_spy.call_count == 0
    assert exc_spy.call_count == 0

    # Now with an open record present, it must refresh -- exactly once each.
    model.insert_record(TimeRecord(None, today, time(9, 0), None, 0, WorkType.REMOTE))

    with targets_patch as targets_spy, exc_patch as exc_spy:
        tab._auto_refresh()

    assert targets_spy.call_count == 1
    assert exc_spy.call_count == 1


def test_standalone_refresh_tree_still_works_without_prefetch(
    db: Database, event_bus: EventBus, settings_manager: SettingsManager
) -> None:
    """Standalone callers (_prev_week/_next_week/_on_period_changed/
    _set_view_mode) call _refresh_tree() alone, with no pre-fetched
    targets/cache -- it must still self-fetch and populate correctly."""
    model = TimeClockModel(db, event_bus)
    today = date.today()
    tab = _make_tab(
        model,
        settings_manager,
        view_mode="month",
        selected_year=today.year,
        selected_month=today.month,
        selected_week_start=today,
    )
    tab._refresh_tree()
    # Should have produced at least the month header row without raising.
    assert len(cast(_FakeTree, tab._tree)._rows) >= 1


def _insert_malformed_row(db: Database, d: date) -> None:
    """Insert a row that fails the TimeRecord invariant (break_minutes 600
    exceeds the shift length) so _row_to_record() silently drops it on d."""
    conn = db.get_connection()
    try:
        with conn:
            conn.execute(
                "INSERT INTO time_record "
                "(date, start_time, end_time, break_minutes, work_type) "
                "VALUES (?, '09:00', '10:00', 600, 'remote');",
                (d.isoformat(),),
            )
    finally:
        conn.close()


def test_refresh_dedups_today_skip_when_period_includes_today(
    db: Database, event_bus: EventBus, settings_manager: SettingsManager
) -> None:
    """When the displayed period includes today, the header's today-fetch and
    the tree's period-fetch both drop the same malformed today-row. The tree
    fetch already covers today, so the surfaced count must be 1 (the single
    bad row) -- _refresh_header_and_tree() must not double-count it as 2."""
    model = TimeClockModel(db, event_bus)
    today = date.today()
    _insert_malformed_row(db, today)

    tab = _make_tab(
        model,
        settings_manager,
        view_mode="month",
        selected_year=today.year,
        selected_month=today.month,
        selected_week_start=today,
    )
    tab._lbl_today = cast(ttk.Label, _CaptureLabel())

    tab._refresh_header_and_tree()

    assert (
        "1 record(s) skipped due to data errors"
        in cast(_CaptureLabel, tab._lbl_today).text
    )


def test_refresh_sums_header_and_tree_skips_for_disjoint_periods(
    db: Database, event_bus: EventBus, settings_manager: SettingsManager
) -> None:
    """When the displayed month does NOT include today, the header's today
    fetch and the tree's period fetch drop disjoint rows, so both returns must
    be summed. A bad row on today (header) plus a bad row in the displayed past
    month (tree) => surfaced count 2, proving both returns are threaded."""
    model = TimeClockModel(db, event_bus)
    today = date.today()
    # A month in the same year guaranteed not to be today's month.
    other_month = 1 if today.month != 1 else 2
    _insert_malformed_row(db, today)
    _insert_malformed_row(db, date(today.year, other_month, 15))

    tab = _make_tab(
        model,
        settings_manager,
        view_mode="month",
        selected_year=today.year,
        selected_month=other_month,
        selected_week_start=today,
    )
    tab._lbl_today = cast(ttk.Label, _CaptureLabel())

    tab._refresh_header_and_tree()

    assert (
        "2 record(s) skipped due to data errors"
        in cast(_CaptureLabel, tab._lbl_today).text
    )


def test_navigation_surfaces_skip_notice_for_new_period(
    db: Database, event_bus: EventBus, settings_manager: SettingsManager
) -> None:
    """A navigation refresh (here _prev_week, a tree-only path before this fix)
    must surface the data-integrity notice for the newly selected period. A
    malformed row in the target week is dropped by the tree fetch, so the
    notice must appear on _lbl_today after navigating there."""
    model = TimeClockModel(db, event_bus)
    today = date.today()
    # Row three days back -- inside the previous week, not "today".
    _insert_malformed_row(db, today - timedelta(days=3))

    tab = _make_tab(
        model,
        settings_manager,
        view_mode="week",
        selected_year=today.year,
        selected_month=today.month,
        selected_week_start=today,
    )
    tab._lbl_today = cast(ttk.Label, _CaptureLabel())
    tab._lbl_week_range = cast(ttk.Label, _FakeWidget())

    # Navigate to the previous week [today-7, today-1], which contains the bad
    # row but not today, so the count is the tree fetch's single drop.
    tab._prev_week()

    assert (
        "1 record(s) skipped due to data errors"
        in cast(_CaptureLabel, tab._lbl_today).text
    )
