"""Vacation Grants dialog — manage a year's ad-hoc extra-hour grants."""

from __future__ import annotations

import logging
import tkinter as tk
from collections.abc import Callable
from datetime import date
from tkinter import messagebox, ttk

from controllers.vacation_controller import VacationController
from core.hebrew_date import to_hebrew_label as _safe_hebrew
from core.timeutil import to_display_date
from domain.enums import WarningCode
from domain.types import VacationGrant
from models.vacation_model import VacationModel
from views.date_picker import make_date_picker
from views.dialog_common import setup_modal_window, validate_note_length

logger = logging.getLogger(__name__)


def _fmt_h(hours: float) -> str:
    return f"{hours:.1f}h"


class VacationGrantDialog(tk.Toplevel):
    """Modal dialog listing, adding, editing, and removing vacation grants.

    Grants are ad-hoc awards of extra vacation hours (their own
    ``vacation_grant`` table, not vacation records) that enlarge a year's
    pool via ``VacationSummary.extra_grant``. The dialog shows every grant
    dated in ``year`` and edits them through ``VacationController`` — each
    successful save/delete publishes ``Event.VACATION_CHANGED``, which the
    opening Vacation tab is already subscribed to.
    """

    def __init__(
        self,
        parent,
        controller: VacationController,
        model: VacationModel,
        year: int,
        **_kwargs,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._model = model
        self._year = year
        # Id of the grant currently loaded into the form for editing, or None
        # when the form is composing a brand-new grant.
        self._editing_id: int | None = None

        # Declared here (bare annotations, no values) so pylint's
        # attribute-defined-outside-init check sees them as belonging to
        # __init__ — the real assignments happen in the _build_* helpers
        # invoked (transitively) from _build_ui below, before __init__
        # returns (mirrors views/settings_dialog.py's SettingsDialog).
        self._tree: ttk.Treeview
        self._date_widget: tk.Widget
        self._get_date: Callable[[], date]
        self._set_date: Callable[[date], object]
        self._var_hours: tk.StringVar
        self._spn_hours: ttk.Spinbox
        self._var_note: tk.StringVar
        self._lbl_error: ttk.Label
        self._btn_save: ttk.Button
        self._btn_new: ttk.Button
        self._btn_remove: ttk.Button

        setup_modal_window(
            self,
            parent,
            f"Vacation Grants — {year}",
            minsize=(480, 440),
            resizable=(True, True),
        )

        self._build_ui()
        self._reload()

        self.wait_window(self)

    # ─────────────────────────── UI Construction ────────────────────────────

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=(16, 12, 16, 8))
        outer.pack(fill="both", expand=True)

        self._build_tree(outer)

        ttk.Separator(outer, orient="horizontal").pack(fill="x", pady=(0, 8))

        self._build_form(outer)

        self._lbl_error = ttk.Label(
            outer, text="", foreground="red", wraplength=440, justify="left"
        )
        self._lbl_error.pack(fill="x", pady=(0, 4))

        self._build_buttons(outer)

    def _build_tree(self, parent: ttk.Frame) -> None:
        tree_frame = ttk.Frame(parent)
        tree_frame.pack(fill="both", expand=True, pady=(0, 8))

        cols = ("date", "hebrew_date", "hours", "note")
        self._tree = ttk.Treeview(
            tree_frame,
            columns=cols,
            show="headings",
            selectmode="browse",
            height=8,
        )
        self._tree.heading("date", text="Date", anchor="center")
        self._tree.column("date", width=100, minwidth=90, stretch=False, anchor="w")
        self._tree.heading("hebrew_date", text="Hebrew Date", anchor="center")
        self._tree.column(
            "hebrew_date", width=150, minwidth=120, stretch=False, anchor="w"
        )
        self._tree.heading("hours", text="Hours", anchor="center")
        self._tree.column("hours", width=70, minwidth=50, stretch=False, anchor="e")
        self._tree.heading("note", text="Note", anchor="center")
        self._tree.column("note", width=180, minwidth=80, stretch=True, anchor="w")

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._tree.pack(side="left", fill="both", expand=True)

        self._tree.bind("<<TreeviewSelect>>", self._on_select)

    def _build_form(self, parent: ttk.Frame) -> None:
        date_row = ttk.Frame(parent)
        date_row.pack(fill="x", pady=(0, 6))
        ttk.Label(date_row, text="Date:", width=8, anchor="e").pack(side="left")
        self._date_widget, self._get_date, self._set_date = make_date_picker(date_row)
        self._date_widget.pack(side="left", padx=(4, 0))

        hours_row = ttk.Frame(parent)
        hours_row.pack(fill="x", pady=(0, 6))
        ttk.Label(hours_row, text="Hours:", width=8, anchor="e").pack(side="left")
        self._var_hours = tk.StringVar(value="8.0")
        self._spn_hours = ttk.Spinbox(
            hours_row,
            textvariable=self._var_hours,
            from_=0.5,
            to=200.0,
            increment=0.5,
            width=8,
            format="%.1f",
        )
        self._spn_hours.pack(side="left", padx=(4, 0))

        note_row = ttk.Frame(parent)
        note_row.pack(fill="x", pady=(0, 10))
        ttk.Label(note_row, text="Note:", width=8, anchor="e").pack(side="left")
        vcmd = (self.register(self._validate_note), "%P")
        self._var_note = tk.StringVar()
        ttk.Entry(
            note_row,
            textvariable=self._var_note,
            width=38,
            validate="key",
            validatecommand=vcmd,
        ).pack(side="left", padx=(4, 0), fill="x", expand=True)

    def _build_buttons(self, parent: ttk.Frame) -> None:
        btn_row = ttk.Frame(parent)
        btn_row.pack(fill="x", pady=(4, 0))
        ttk.Button(btn_row, text="Close", command=self.destroy).pack(
            side="right", padx=(6, 0)
        )
        self._btn_save = ttk.Button(
            btn_row, text="Save", style="Accent.TButton", command=self._on_save
        )
        self._btn_save.pack(side="right")
        self._btn_new = ttk.Button(btn_row, text="New", command=self._clear_form)
        self._btn_new.pack(side="left")
        self._btn_remove = ttk.Button(
            btn_row, text="🗑 Remove", style="Danger.TButton", command=self._on_remove
        )
        self._btn_remove.pack(side="left", padx=(6, 0))

    # ─────────────────────────── Validation ─────────────────────────────────

    def _validate_note(self, proposed: str) -> bool:
        return validate_note_length(proposed)

    # ─────────────────────────── Data / Form ────────────────────────────────

    def _reload(self) -> None:
        for item in self._tree.get_children():
            self._tree.delete(item)
        for grant in self._model.get_grants_for_year(self._year):
            self._tree.insert(
                "",
                "end",
                iid=f"grant_{grant.id}",
                values=(
                    to_display_date(grant.date),
                    _safe_hebrew(grant.date),
                    _fmt_h(grant.hours),
                    grant.note or "",
                ),
            )
        self._clear_form()

    def _clear_form(self) -> None:
        self._editing_id = None
        # New grants default to today when today falls in this year, else to
        # Jan 1 of the year being managed — so a freshly saved grant is always
        # visible in this dialog's (year-scoped) list.
        today = date.today()
        default = today if today.year == self._year else date(self._year, 1, 1)
        self._set_date(default)
        self._var_hours.set("8.0")
        self._var_note.set("")
        selection = self._tree.selection()
        if selection:
            self._tree.selection_remove(*selection)
        self._lbl_error.config(text="")

    def _on_select(self, _event: object = None) -> None:
        selection = self._tree.selection()
        if not selection:
            return
        iid = selection[0]
        if not iid.startswith("grant_"):
            return
        try:
            grant_id = int(iid[len("grant_") :])
        except ValueError:
            return
        grant = self._model.get_grant_by_id(grant_id)
        if grant is None:
            # The selected grant vanished (e.g. deleted in a race). Reload to
            # drop the phantom row and reset the form, so a stale ``_editing_id``
            # from a previously loaded grant can't leak into the next Save.
            self._reload()
            return
        self._editing_id = grant.id
        self._set_date(grant.date)
        self._var_hours.set(f"{grant.hours:.1f}")
        self._var_note.set(grant.note or "")
        self._lbl_error.config(text="")

    # ─────────────────────────── Actions ────────────────────────────────────

    def _on_save(self) -> None:
        self._lbl_error.config(text="")
        try:
            grant_date: date = self._get_date()
        except (ValueError, IndexError) as exc:
            logger.warning(
                "Could not parse date %r for vacation grant: %s",
                self._date_widget.get(),
                exc,
            )
            self._lbl_error.config(text="Invalid date.")
            return

        try:
            hours = float(self._var_hours.get())
        except ValueError:
            self._lbl_error.config(text="Hours must be a number greater than zero.")
            return

        note_s = self._var_note.get().strip()
        try:
            grant = VacationGrant(
                id=self._editing_id,
                date=grant_date,
                hours=hours,
                note=note_s or None,
            )
        except ValueError as exc:
            self._lbl_error.config(text=str(exc))
            return

        result = self._controller.save_grant(grant)
        if result.ok:
            self._reload()
        else:
            self._lbl_error.config(text="\n".join(result.errors))

    def _on_remove(self) -> None:
        self._lbl_error.config(text="")
        if self._editing_id is None:
            messagebox.showinfo(
                "Remove Grant", "Select a grant to remove.", parent=self
            )
            return
        if not messagebox.askyesno(
            "Confirm Remove",
            "Permanently remove this vacation grant?",
            icon="warning",
            parent=self,
        ):
            return
        result = self._controller.delete_grant(self._editing_id)
        if result.ok:
            self._reload()
            return
        # A RECORD_NOT_FOUND race means the grant was already gone — reloading
        # drops the phantom row silently; any other error is surfaced.
        if WarningCode.RECORD_NOT_FOUND.value not in result.errors:
            messagebox.showerror("Remove Failed", "\n".join(result.errors), parent=self)
        self._reload()
