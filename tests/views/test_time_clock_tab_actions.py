"""Regression tests for TimeClockTab's RECORD_NOT_FOUND stale-record-race
handling in ``_do_edit()``/``_do_delete()``, and for
``_handle_vanished_open_record()`` -- reached from both the direct
clock-out button and the "pick record to close" flow (no live Tk display
needed).

This repo's CI runs headless with no X display (see tests/views/
test_help_viewer_dialogs.py and tests/views/test_time_clock_tab_dedup.py
for the same constraint on other view modules), so TimeClockTab is built
via ``TimeClockTab.__new__`` (bypassing ``__init__``, which constructs
real ttk widgets) with just the attributes each method under test
actually touches -- mirroring the ``_make_tab`` bypass pattern in
tests/views/test_time_clock_tab_dedup.py and tests/views/
test_miliuim_tab.py. ``TimeRecordDialog`` (a ``tk.Toplevel`` subclass) is
patched out at the module level it is imported into, and
``_pick_record_to_close()`` -- which builds its own ad hoc
``tk.Toplevel``/``tk.Listbox`` picker dialog inline rather than via a
separate dialog class -- has every tk/ttk constructor it touches mocked
out, mirroring the closure-testing pattern in tests/views/
test_help_viewer_dialogs.py: the "Clock Out" button's ``command`` kwarg
is captured via a ``side_effect`` and invoked directly in place of a real
click.
"""

from datetime import date, time
from tkinter import ttk
from typing import cast
from unittest import mock

from core.events import EventBus
from db.database import Database
from domain.enums import WarningCode, WorkType
from domain.types import Result, TimeRecord
from models.time_clock_model import TimeClockModel
from views.time_clock_tab import TimeClockTab


class _FakeTree:
    """Stand-in for the ttk.Treeview: only ``selection()`` is exercised by
    ``_get_selected_record_id()``, which is all ``_do_edit()``/``_do_delete()``
    need."""

    def __init__(self, selected_iid: str | None = None) -> None:
        self._selected_iid = selected_iid

    def selection(self):
        return (self._selected_iid,) if self._selected_iid is not None else ()


def _make_tab(
    model: TimeClockModel,
    controller: object = None,
    selected_iid: str | None = None,
) -> TimeClockTab:
    """Builds a TimeClockTab without running __init__ / constructing real
    Tk widgets -- only the attributes touched by the methods under test
    are set."""
    tab = TimeClockTab.__new__(TimeClockTab)
    tab.model = model
    tab.controller = controller if controller is not None else mock.Mock()
    tab.settings = mock.Mock()
    tab._tree = cast(ttk.Treeview, _FakeTree(selected_iid))
    tab._theme_mode = "light"
    return tab


def _insert_closed_record(model: TimeClockModel, day: date) -> int:
    return model.insert_record(
        TimeRecord(None, day, time(9, 0), time(10, 0), 0, WorkType.REMOTE)
    )


def _insert_open_record(model: TimeClockModel, day: date) -> int:
    return model.insert_record(
        TimeRecord(None, day, time(9, 0), None, 0, WorkType.REMOTE)
    )


# ─────────────────────────── _do_edit() ──────────────────────────────────


def test_do_edit_record_vanished_true_triggers_refresh(
    db: Database, event_bus: EventBus
) -> None:
    """When the modal ``TimeRecordDialog``'s save hits the RECORD_NOT_FOUND
    stale-record race, ``record_vanished`` comes back ``True`` and
    ``_do_edit()`` must call ``self._refresh()`` to clear the now-phantom
    row -- mirrors the equivalent test in tests/views/test_miliuim_tab.py."""
    model = TimeClockModel(db, event_bus)
    today = date.today()
    rec_id = _insert_closed_record(model, today)
    tab = _make_tab(model, selected_iid=f"rec_{rec_id}")
    refresh_mock = mock.Mock()
    tab._refresh = refresh_mock

    with (
        mock.patch("views.time_clock_tab.messagebox") as messagebox_mock,
        mock.patch("views.time_clock_tab.TimeRecordDialog") as dialog_mock,
    ):
        dialog_mock.return_value.record_vanished = True
        tab._do_edit()

    messagebox_mock.showwarning.assert_not_called()
    refresh_mock.assert_called_once()


def test_do_edit_record_vanished_false_does_not_refresh(
    db: Database, event_bus: EventBus
) -> None:
    """The other half of the ``dlg.record_vanished`` branch: a normal save
    (no stale-record race) must NOT trigger the extra refresh."""
    model = TimeClockModel(db, event_bus)
    today = date.today()
    rec_id = _insert_closed_record(model, today)
    tab = _make_tab(model, selected_iid=f"rec_{rec_id}")
    refresh_mock = mock.Mock()
    tab._refresh = refresh_mock

    with (
        mock.patch("views.time_clock_tab.messagebox") as messagebox_mock,
        mock.patch("views.time_clock_tab.TimeRecordDialog") as dialog_mock,
    ):
        dialog_mock.return_value.record_vanished = False
        tab._do_edit()

    messagebox_mock.showwarning.assert_not_called()
    refresh_mock.assert_not_called()


# ─────────────────────────── _do_delete() ────────────────────────────────


def test_do_delete_record_not_found_shows_info_and_refreshes(
    db: Database, event_bus: EventBus
) -> None:
    """``_do_delete()``'s RECORD_NOT_FOUND branch (the stale-record race
    where the row was already removed elsewhere) must show the friendly
    "Record Already Deleted" info box -- not the generic error box -- and
    call ``self._refresh()`` to clear the phantom row."""
    model = TimeClockModel(db, event_bus)
    today = date.today()
    rec_id = _insert_closed_record(model, today)
    controller = mock.Mock()
    controller.delete_record.return_value = Result(
        ok=False, errors=(WarningCode.RECORD_NOT_FOUND.value,)
    )
    tab = _make_tab(model, controller=controller, selected_iid=f"rec_{rec_id}")
    refresh_mock = mock.Mock()
    tab._refresh = refresh_mock

    with (
        mock.patch("views.time_clock_tab.messagebox") as messagebox_mock,
        mock.patch("views.record_tab_common.messagebox") as common_mb,
    ):
        messagebox_mock.askyesno.return_value = True
        tab._do_delete()

    common_mb.showinfo.assert_called_once()
    common_mb.showerror.assert_not_called()
    refresh_mock.assert_called_once()


# ─────────────────────── _handle_vanished_open_record() ──────────────────


def test_handle_vanished_open_record_shows_info_and_refreshes(
    db: Database, event_bus: EventBus
) -> None:
    """Must show the clock-out-specific "Nothing to Clock Out" info box
    (issue #38: this benign self-healing stale-record race is presented as
    info, matching the delete race and the tray -- not a warning) and call
    self._refresh() unconditionally."""
    model = TimeClockModel(db, event_bus)
    tab = _make_tab(model)
    refresh_mock = mock.Mock()
    cancel_mock = mock.Mock()
    tab._refresh = refresh_mock
    tab._cancel_auto_refresh = cancel_mock

    with mock.patch("views.time_clock_tab.messagebox") as messagebox_mock:
        tab._handle_vanished_open_record()

    messagebox_mock.showinfo.assert_called_once()
    messagebox_mock.showwarning.assert_not_called()
    refresh_mock.assert_called_once()


def test_handle_vanished_open_record_cancels_auto_refresh_when_no_open_records_remain(
    db: Database, event_bus: EventBus
) -> None:
    """No open records left after the refresh (the common case: the
    vanished record was the only open one) -- the 60s auto-refresh timer
    must be cancelled, since nothing is left to poll for."""
    model = TimeClockModel(db, event_bus)
    tab = _make_tab(model)
    refresh_mock = mock.Mock()
    cancel_mock = mock.Mock()
    tab._refresh = refresh_mock
    tab._cancel_auto_refresh = cancel_mock

    with mock.patch("views.time_clock_tab.messagebox"):
        tab._handle_vanished_open_record()

    cancel_mock.assert_called_once()


def test_handle_vanished_open_record_keeps_auto_refresh_when_open_records_remain(
    db: Database, event_bus: EventBus
) -> None:
    """Other open records still exist (e.g. one of several concurrent
    open records vanished, not the last one) -- the auto-refresh timer
    must NOT be cancelled, since there's still something to poll for."""
    model = TimeClockModel(db, event_bus)
    today = date.today()
    _insert_open_record(model, today)
    tab = _make_tab(model)
    refresh_mock = mock.Mock()
    cancel_mock = mock.Mock()
    tab._refresh = refresh_mock
    tab._cancel_auto_refresh = cancel_mock

    with mock.patch("views.time_clock_tab.messagebox"):
        tab._handle_vanished_open_record()

    cancel_mock.assert_not_called()


# ───────────────────── Call site 1: _do_clock_out() ───────────────────────


def test_do_clock_out_record_not_found_triggers_handle_vanished(
    db: Database, event_bus: EventBus
) -> None:
    """The direct clock-out button's RECORD_NOT_FOUND result must route
    through ``_handle_vanished_open_record()`` -- not the generic
    "Clock Out Failed" error box."""
    model = TimeClockModel(db, event_bus)
    controller = mock.Mock()
    controller.clock_out.return_value = Result(
        ok=False, errors=(WarningCode.RECORD_NOT_FOUND.value,)
    )
    tab = _make_tab(model, controller=controller)
    handle_mock = mock.Mock()
    tab._handle_vanished_open_record = handle_mock

    with mock.patch("views.time_clock_tab.messagebox") as messagebox_mock:
        tab._do_clock_out()

    handle_mock.assert_called_once()
    messagebox_mock.showerror.assert_not_called()
    controller.clock_out.assert_called_once_with()


# ─────────────────── Call site 2: _pick_record_to_close() ────────────────


def test_pick_record_to_close_confirm_record_not_found_triggers_handle_vanished(
    db: Database, event_bus: EventBus
) -> None:
    """The second call site: inside the "pick record to close" dialog's
    nested ``_confirm()`` closure, reached when the user has multiple open
    records and picks one to close, but that specific record was deleted
    elsewhere before the click landed. Building the real picker dialog
    needs a live Tk display (``tk.Toplevel``/``tk.Listbox``), so every
    tk/ttk constructor it touches is mocked out, and the "Clock Out"
    button's captured ``command`` callback is invoked directly in place of
    a real click."""
    model = TimeClockModel(db, event_bus)
    today = date.today()
    rec_id = _insert_open_record(model, today)
    open_rec = model.get_record_by_id(rec_id)
    controller = mock.Mock()
    controller.clock_out.return_value = Result(
        ok=False, errors=(WarningCode.RECORD_NOT_FOUND.value,)
    )
    tab = _make_tab(model, controller=controller)
    handle_mock = mock.Mock()
    tab._handle_vanished_open_record = handle_mock

    listbox_mock = mock.MagicMock()
    listbox_mock.curselection.return_value = (0,)
    confirm_holder: dict[str, object] = {}

    def _button_side_effect(*_args: object, **kwargs: object) -> mock.MagicMock:
        if kwargs.get("text") == "Clock Out":
            confirm_holder["confirm"] = kwargs["command"]
        return mock.MagicMock()

    with (
        mock.patch.object(model, "get_open_records", return_value=[open_rec]),
        mock.patch("views.time_clock_tab.tk.Toplevel"),
        mock.patch("views.time_clock_tab.setup_modal_window"),
        mock.patch("views.time_clock_tab.ttk.Label"),
        mock.patch("views.time_clock_tab.ttk.Frame"),
        mock.patch("views.time_clock_tab.tk.Listbox", return_value=listbox_mock),
        mock.patch("views.time_clock_tab.ttk.Button", side_effect=_button_side_effect),
    ):
        tab._pick_record_to_close()

    assert "confirm" in confirm_holder
    confirm = confirm_holder["confirm"]
    assert callable(confirm)
    confirm()

    handle_mock.assert_called_once()
    controller.clock_out.assert_called_once_with(record_id=rec_id)
