"""Shared selection/period-filter behavior for tabs backed by a Treeview
of ``rec_<id>`` rows plus Add/Edit/Remove buttons and a year/month filter.

Subclasses provide the widgets and state this mixin operates on (declared
below as bare annotations so type checkers see them) and their own
``_do_edit``/``_refresh``/``_do_add``/``_do_delete`` hooks.
"""

from __future__ import annotations

import logging
import tkinter as tk
from tkinter import ttk
from typing import Callable

from core.timeutil import MONTH_NAMES

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

    def _refresh(self, **_kw: object) -> None:
        raise NotImplementedError

    def _do_edit(self) -> None:
        raise NotImplementedError

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

    def _on_destroy(self, _event: object = None) -> None:
        self._clear_unsubs()
