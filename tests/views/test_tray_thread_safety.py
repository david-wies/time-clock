"""Regression test for the SystemTray cross-thread DB-query bug (§21.4).

This repo's CI runs headless with no X display (see tests/views/
test_help_viewer_dialogs.py and test_time_clock_tab_dedup.py for the same
constraint on other view modules), so this test never calls
``SystemTray.start()`` (which spawns pystray's real background icon
thread) -- it only exercises ``_build_menu()`` and ``_on_records_changed()``
directly, which is all that's needed to prove the regression is fixed.

Background: pystray evaluates ``MenuItem(enabled=...)`` predicates lazily,
on its own background icon-rendering thread (not the Tk main thread), on
backends that actually render menus (Windows, Linux GTK/AppIndicator).
Before the fix, ``_build_menu()``'s "Clock In"/"Clock Out" predicates
called ``self._is_clocked_in()`` directly, which queries the model's
shared, single-thread-affine ``sqlite3.Connection`` -- a cross-thread call
that raises ``sqlite3.ProgrammingError`` once ``Database.get_connection()``
started returning one persistent connection instead of a fresh one per
call. The fix caches clocked-in state on the main thread
(``self._clocked_in_cache``), refreshed in ``_on_records_changed()``
(documented as running on the Tk main thread via the synchronous
EventBus), and has the menu predicates read the cache instead of querying
the model.
"""
from datetime import date, time
from unittest import mock

import pytest

from core.events import EventBus
from db.database import Database
from domain.enums import WorkType
from domain.types import TimeRecord
from models.time_clock_model import TimeClockModel
from settings import SettingsManager
from views.tray import SystemTray


class _FakeRoot:
    """Stand-in for tk.Tk -- SystemTray.__init__ never calls tkinter."""

    def protocol(self, *_a, **_kw) -> None:
        pass

    def after(self, *_a, **_kw) -> str:
        return "after_id"


def _make_tray(
    model: TimeClockModel, settings: SettingsManager, bus: EventBus
) -> SystemTray:
    return SystemTray(
        root=_FakeRoot(),  # type: ignore[arg-type]
        controller=mock.Mock(),  # type: ignore[arg-type]
        model=model,
        settings=settings,
        bus=bus,
    )


def _menu_items(tray: SystemTray) -> tuple:
    menu = tray._build_menu()
    return tuple(menu.items)


def test_menu_predicates_read_cache_without_querying_model(
    db: Database, event_bus: EventBus, settings_manager: SettingsManager
) -> None:
    """The Clock In / Clock Out `enabled` predicates must read
    `self._clocked_in_cache` -- never call into the model -- because
    pystray may evaluate them from its own background thread, which would
    violate the shared connection's single-thread affinity."""
    model = TimeClockModel(db, event_bus)
    tray = _make_tray(model, settings_manager, event_bus)

    clock_in_item, clock_out_item, *_rest = _menu_items(tray)
    assert clock_in_item.text == "Clock In"
    assert clock_out_item.text == "Clock Out"

    with mock.patch.object(
        model, "get_open_records_for_date",
        wraps=model.get_open_records_for_date,
    ) as spy:
        # Default cache (set in __init__, before any main-thread refresh)
        # is False -> not clocked in.
        assert clock_in_item.enabled is True
        assert clock_out_item.enabled is False

    spy.assert_not_called()


def test_on_records_changed_refreshes_cache_from_model(
    db: Database, event_bus: EventBus, settings_manager: SettingsManager
) -> None:
    """`_on_records_changed()` is documented as running on the tkinter
    main thread via the synchronous EventBus -- it is the correct (and
    only) place that may re-query the model to refresh the cache."""
    model = TimeClockModel(db, event_bus)
    tray = _make_tray(model, settings_manager, event_bus)

    assert tray._clocked_in_cache is False

    with mock.patch.object(
        model, "get_open_records_for_date",
        wraps=model.get_open_records_for_date,
    ) as spy:
        tray._on_records_changed()
    spy.assert_called_once()
    assert tray._clocked_in_cache is False

    today = date.today()
    model.insert_record(
        TimeRecord(None, today, time(9, 0), None, 0, WorkType.REMOTE)
    )

    tray._on_records_changed()
    assert tray._clocked_in_cache is True

    clock_in_item, clock_out_item, *_rest = _menu_items(tray)
    assert clock_in_item.enabled is False
    assert clock_out_item.enabled is True
