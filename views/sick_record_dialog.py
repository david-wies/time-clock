"""Add / Edit Sick Record dialog."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox
from datetime import date
from typing import Optional

from controllers.sickness_controller import SicknessController
from models.sickness_model import SicknessModel
from domain.types import SicknessRecord
from views.date_picker import make_date_picker


class SickRecordDialog(tk.Toplevel):

    def __init__(
        self,
        parent,
        controller: SicknessController,
        model: SicknessModel,
        record: Optional[SicknessRecord] = None,
        **_kwargs,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._model = model
        self._record = record

        editing = record is not None
        self.title("Edit Sick Record" if editing else "Add Sick Record")
        self.resizable(False, False)
        self.minsize(400, 300)
        self.transient(parent)
        self.grab_set()

        self._build_ui()
        self._populate(record)
        self._update_day_equiv()

        self.wait_window(self)

    # ─────────────────────────── UI Construction ────────────────────────────

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=(16, 12, 16, 8))
        outer.pack(fill="both", expand=True)

        # ── Date ──────────────────────────────────────────────────────────────
        date_row = ttk.Frame(outer)
        date_row.pack(fill="x", pady=(0, 6))
        ttk.Label(date_row, text="Date:", width=8, anchor="e").pack(side="left")

        dp_result = make_date_picker(date_row)
        if isinstance(dp_result, tuple):
            self._date_widget, self._get_date, self._set_date = dp_result
        else:
            self._date_widget = dp_result
            self._get_date = dp_result.get_date
            self._set_date = dp_result.set_date
        self._date_widget.pack(side="left", padx=(4, 0))

        # ── Hours + live day-equivalent ───────────────────────────────────────
        hours_row = ttk.Frame(outer)
        hours_row.pack(fill="x", pady=(0, 6))
        ttk.Label(hours_row, text="Hours:", width=8, anchor="e").pack(side="left")
        self._var_hours = tk.StringVar(value="8.0")
        self._spn_hours = ttk.Spinbox(
            hours_row, textvariable=self._var_hours,
            from_=0.5, to=24.0, increment=0.5, width=8,
            format="%.1f",
        )
        self._spn_hours.pack(side="left", padx=(4, 8))
        self._lbl_day_equiv = ttk.Label(hours_row, text="= --", foreground="gray")
        self._lbl_day_equiv.pack(side="left")

        # ── Note ──────────────────────────────────────────────────────────────
        note_row = ttk.Frame(outer)
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

        # ── Error label ───────────────────────────────────────────────────────
        self._lbl_error = ttk.Label(
            outer, text="", foreground="red", wraplength=368, justify="left"
        )
        self._lbl_error.pack(fill="x", pady=(0, 4))

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_row = ttk.Frame(outer)
        btn_row.pack(fill="x", pady=(4, 0))
        ttk.Button(btn_row, text="Cancel", command=self.destroy).pack(
            side="right", padx=(6, 0)
        )
        ttk.Button(btn_row, text="Save", command=self._on_save).pack(side="right")

        # ── Live-update traces ────────────────────────────────────────────────
        self._var_hours.trace_add("write", lambda *_: self._update_day_equiv())

    # ─────────────────────────── Data Population ────────────────────────────

    def _populate(self, record: Optional[SicknessRecord]) -> None:
        if record is None:
            self._set_date(date.today())
            self._var_hours.set("8.0")
            self._var_note.set("")
        else:
            self._set_date(record.date)
            self._var_hours.set(f"{record.hours:.1f}")
            self._var_note.set(record.note or "")

    # ─────────────────────────── Live Update ────────────────────────────────

    def _update_day_equiv(self) -> None:
        try:
            rec_date = self._get_date()
            hours = float(self._var_hours.get())
            equiv = self._model.get_day_equivalent(rec_date, hours)
            self._lbl_day_equiv.config(text=f"= {equiv:.2f} day(s)")
        except Exception:
            self._lbl_day_equiv.config(text="= --")

    # ─────────────────────────── Validation ─────────────────────────────────

    def _validate_note(self, proposed: str) -> bool:
        return len(proposed) <= 500

    # ─────────────────────────── Save ────────────────────────────────────────

    def _on_save(self, confirm_over_balance: bool = False) -> None:
        self._lbl_error.config(text="")
        field_errors: list[str] = []

        try:
            rec_date: Optional[date] = self._get_date()
        except Exception:
            field_errors.append("Invalid date.")
            rec_date = None

        try:
            hours = float(self._var_hours.get())
        except ValueError:
            field_errors.append("Hours must be a number between 0.5 and 24.")
            hours = 0.0

        if field_errors:
            self._lbl_error.config(text="\n".join(field_errors))
            return

        note_s = self._var_note.get().strip()
        record = SicknessRecord(
            id=self._record.id if self._record is not None else None,
            date=rec_date,
            hours=hours,
            note=note_s or None,
        )

        result = self._controller.save_record(record, confirm_over_balance=confirm_over_balance)
        if result.ok:
            self.destroy()
        elif "OVER_BALANCE_WARNING" in result.errors:
            if messagebox.askyesno(
                "Balance Exceeded",
                "This exceeds your remaining sick day balance.\nSave anyway?",
                parent=self,
            ):
                self._on_save(confirm_over_balance=True)
        else:
            self._lbl_error.config(text="\n".join(result.errors))
