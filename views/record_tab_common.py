"""Shared selection/period-filter behavior for tabs backed by a Treeview
of ``rec_<id>`` rows plus Add/Edit/Remove buttons and a year/month filter.

Subclasses provide the widgets and state this mixin operates on (declared
below as bare annotations so type checkers see them) and their own
``_do_edit``/``_refresh``/``_do_add``/``_do_delete`` hooks.
"""

from __future__ import annotations

import logging
import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk

from core.timeutil import MONTH_NAMES
from domain.enums import RECORD_NOT_FOUND_MESSAGE, WarningCode
from domain.types import Result

logger = logging.getLogger(__name__)


class RecordTabMixin:
    """Mixin for VacationTab/MiliuimTab/SicknessTab/TimeClockTab-style tabs."""

    _tree: ttk.Treeview
    _btn_edit: ttk.Button
    _btn_delete: ttk.Button
    _var_year: tk.StringVar
    _var_month: tk.StringVar
    _selected_year: int
    _selected_month: int
    _unsubs: list[Callable[[], None]]
    root: tk.Misc

    def _refresh(self, **_kw: object) -> None:
        raise NotImplementedError

    def _do_edit(self) -> None:
        raise NotImplementedError

    def _handle_delete_result(
        self, result: Result, *, already_gone_title: str, error_title: str
    ) -> None:
        """Shared ``_do_delete`` result handling for record tabs.

        On the RECORD_NOT_FOUND stale-record race (the selected row was
        already deleted elsewhere) shows an informational box titled
        ``already_gone_title`` and refreshes so the phantom row disappears;
        the race is benign and self-healing, so it is ``showinfo``, not
        ``showwarning`` (unlike the dialog save-race, which discards edits).
        ``already_gone_title``/``error_title`` are passed in rather than
        fixed here because they are keyed to each tab's Delete/Remove verb
        ("Record Already Deleted"/"Delete Failed" for the time-clock tab,
        "Record Already Removed"/"Remove Failed" for the others). Any other
        error surfaces via ``showerror``; a successful result is a no-op
        (the model's mutation event already drives the refresh)."""
        if result.ok:
            return
        if WarningCode.RECORD_NOT_FOUND.value in result.errors:
            messagebox.showinfo(
                already_gone_title, RECORD_NOT_FOUND_MESSAGE, parent=self
            )
            self._refresh()
            return
        messagebox.showerror(error_title, "\n".join(result.errors), parent=self)

    def _after_record_dialog(self, dialog: object) -> None:
        """Refresh epilogue to run after a modal record-edit dialog closes.

        If the dialog's save hit the RECORD_NOT_FOUND stale-record race it
        set ``record_vanished`` and published no mutation event, so refresh
        explicitly to drop the phantom row; otherwise the model's own event
        already drove the refresh and this is a no-op."""
        if getattr(dialog, "record_vanished", False):
            self._refresh()

    def _get_selected_record_id(self) -> int | None:
        """Returns the id encoded in the selected row's ``rec_<id>`` iid, if any."""
        sel = self._tree.selection()
        if not sel:
            return None
        iid = sel[0]
        if iid.startswith("rec_"):
            try:
                return int(iid[4:])
            except ValueError:
                return None
        return None

    def _update_edit_delete_states(self) -> None:
        """Enables Edit/Remove only when a record row is selected."""
        state = "normal" if self._get_selected_record_id() is not None else "disabled"
        self._btn_edit.config(state=state)
        self._btn_delete.config(state=state)

    def _update_button_states(self) -> None:
        self._update_edit_delete_states()

    def _on_double_click(self, event: tk.Event) -> None:
        iid = self._tree.identify_row(event.y)
        if iid and iid.startswith("rec_"):
            self._tree.selection_set(iid)
            self._do_edit()

    def _on_tree_select(self, _event: object = None) -> None:
        self._update_edit_delete_states()

    def _on_period_changed(self, _event: object = None) -> None:
        """Reads the year/month combobox filter and re-runs ``_refresh()``."""
        try:
            self._selected_year = int(self._var_year.get())
        except ValueError:
            logger.exception(
                "Failed to parse year filter combobox value: %r",
                self._var_year.get(),
            )
            return
        month_name = self._var_month.get()
        if month_name == "All":
            self._selected_month = 0
        elif month_name in MONTH_NAMES:
            idx = MONTH_NAMES.index(month_name)
            self._selected_month = idx if idx > 0 else 0
        self._refresh()

    @staticmethod
    def _append_skip_notice(label: ttk.Label, skipped: int) -> None:
        """Appends a data-integrity notice to `label`'s current text when a
        model's most recent list-fetch call (surfaced via its
        ``last_skipped_count`` attribute -- see models/*_model.py's
        ``_rows_to_records()``) silently dropped malformed rows.

        No-ops when `skipped` is 0, and preserves whatever text `label`
        already shows (e.g. a balance/summary line set earlier in the same
        refresh) rather than overwriting it, so callers can call this last
        in their refresh method regardless of which label already carries
        the primary status text for that tab.
        """
        if skipped <= 0:
            return
        current = label.cget("text")
        notice = f"{skipped} record(s) skipped due to data errors"
        label.config(text=f"{current}  ({notice})" if current else f"({notice})")

    def _clear_unsubs(self) -> None:
        """Unsubscribes every EventBus subscription registered in ``_unsubs``.

        Best-effort: an individual unsub failing must not stop the rest from
        running, so failures are logged rather than raised (called from a
        ``<Destroy>`` binding, where a raised exception has nowhere useful to go).
        """
        for unsub in self._unsubs:
            try:
                unsub()
            except Exception:  # pylint: disable=broad-exception-caught
                logger.exception("Error while unsubscribing from EventBus")
        self._unsubs.clear()

    def _bind_shortcut(self, sequence: str, handler: Callable[[], object]) -> None:
        """Registers a global keyboard shortcut via ``bind_all``, wrapped in
        ``_guard_visible`` so it only fires while this tab is the visible
        one, and records the binding so ``_on_destroy`` can undo it.

        Lazily initializes ``self._shortcut_binds`` on first use so callers
        don't need to set it up in ``__init__``, matching how ``_unsubs`` is
        otherwise the only piece of destroy-time cleanup state on this mixin.
        """
        if not hasattr(self, "_shortcut_binds"):
            self._shortcut_binds: list[tuple[str, str]] = []
        funcid = self.root.bind_all(sequence, self._guard_visible(handler), add=True)
        self._shortcut_binds.append((sequence, funcid))

    def _clear_shortcuts(self) -> None:
        """Unbinds every shortcut registered via ``_bind_shortcut``.

        Uses ``root.unbind(sequence, funcid)`` -- a binding removed by its
        specific funcid -- rather than ``root.unbind_all(sequence)``, which
        would strip *every* handler bound to that sequence process-wide,
        including ones ``add=True``-registered by other tab instances
        sharing this root. Best-effort like ``_clear_unsubs``: an individual
        unbind failing must not stop the rest from running (called from a
        ``<Destroy>`` binding, where a raised exception has nowhere useful
        to go).
        """
        for sequence, funcid in getattr(self, "_shortcut_binds", []):
            try:
                self.root.unbind(sequence, funcid)
            except Exception:  # pylint: disable=broad-exception-caught
                logger.exception("Error while unbinding shortcut %r", sequence)
        self._shortcut_binds = []

    def _on_destroy(self, _event: object = None) -> None:
        self._clear_unsubs()
        self._clear_shortcuts()

    def _guard_visible(
        self, fn: Callable[[], object]
    ) -> Callable[[object | None], None]:
        """Wraps a shortcut handler so it only fires when this tab frame is
        the currently visible one.

        ``bind_all`` is process-wide: all tab frames coexist in the
        Notebook, so without this check a shortcut fires on every hidden tab
        too, not just the one currently selected/visible.
        """

        def _handler(_e: object = None) -> None:
            try:
                if self.winfo_exists() and self.winfo_ismapped():
                    fn()
            except tk.TclError:
                logger.debug(
                    "Ignoring TclError from shortcut handler firing on a "
                    "widget destroyed between the winfo check and the call "
                    "(expected race)",
                    exc_info=True,
                )

        return _handler
