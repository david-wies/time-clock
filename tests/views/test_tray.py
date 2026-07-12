"""Regression test for SystemTray's clock-out RECORD_NOT_FOUND
stale-record-race handling (no live Tk display or real pystray icon
needed).

This repo's CI runs headless with no X display (see tests/views/
test_tray_thread_safety.py for the same constraint on this module), so
this test never calls ``SystemTray.start()`` (which spawns pystray's real
background icon thread and a live Tk root) -- it only exercises
``_do_clock_out()`` directly, mirroring ``test_tray_thread_safety.py``'s
``_FakeRoot``/``_make_tray`` bypass pattern. Per CLAUDE.md's tray-threading
rule, ``_do_clock_out()`` itself is a main-thread action (reached via
``root.after(0, ...)`` marshaling from the pystray callback thread -- see
``_tray_clock_out()``); calling it directly here is equivalent to that
marshaled call already having landed on the main thread, so no thread
simulation is needed to exercise its body.
"""

from unittest import mock

from core.events import EventBus
from db.database import Database
from domain.enums import WarningCode
from domain.types import Result
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
    model: TimeClockModel, settings: SettingsManager, bus: EventBus, controller: object
) -> SystemTray:
    return SystemTray(
        root=_FakeRoot(),  # type: ignore[arg-type]
        controller=controller,  # type: ignore[arg-type]
        model=model,
        settings=settings,
        bus=bus,
    )


def test_do_clock_out_record_not_found_shows_info_and_resyncs_icon(
    db: Database, event_bus: EventBus, settings_manager: SettingsManager
) -> None:
    """The stale-record race (the open record was already deleted
    elsewhere) must show the friendly "Nothing to Clock Out" info box --
    not the generic "Clock Out Failed" error box -- and call
    ``self._on_records_changed()`` to re-sync the tray icon/title from the
    DB, since no mutation event was published for this failed call."""
    model = TimeClockModel(db, event_bus)
    controller = mock.Mock()
    controller.clock_out.return_value = Result(
        ok=False, errors=(WarningCode.RECORD_NOT_FOUND.value,)
    )
    tray = _make_tray(model, settings_manager, event_bus, controller)
    on_records_changed_mock = mock.Mock()
    tray._on_records_changed = on_records_changed_mock

    with mock.patch("views.tray.messagebox") as messagebox_mock:
        tray._do_clock_out()

    messagebox_mock.showinfo.assert_called_once()
    messagebox_mock.showerror.assert_not_called()
    on_records_changed_mock.assert_called_once()


def test_do_clock_out_other_failure_shows_error_and_does_not_resync(
    db: Database, event_bus: EventBus, settings_manager: SettingsManager
) -> None:
    """Contrast case: a non-RECORD_NOT_FOUND failure must fall through to
    the generic error box, and must NOT trigger the RECORD_NOT_FOUND
    branch's icon re-sync -- proving the RECORD_NOT_FOUND check above is
    not simply always true."""
    model = TimeClockModel(db, event_bus)
    controller = mock.Mock()
    controller.clock_out.return_value = Result(ok=False, errors=("SOME_OTHER_ERROR",))
    tray = _make_tray(model, settings_manager, event_bus, controller)
    on_records_changed_mock = mock.Mock()
    tray._on_records_changed = on_records_changed_mock

    with mock.patch("views.tray.messagebox") as messagebox_mock:
        tray._do_clock_out()

    messagebox_mock.showerror.assert_called_once()
    messagebox_mock.showinfo.assert_not_called()
    on_records_changed_mock.assert_not_called()
