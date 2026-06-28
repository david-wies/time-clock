"""Add / Edit Vacation Record dialog."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox
from datetime import date
from typing import Optional

from controllers.vacation_controller import VacationController
from models.vacation_model import VacationModel
from domain.enums import VacationType
from domain.types import VacationRecord
from views.date_picker import make_date_picker

_VTYPE_OPTIONS: list[tuple[VacationType, str]] = [
    (VacationType.ANNUAL_LEAVE, "Annual Leave"),
    (VacationType.PUBLIC_HOLIDAY, "Public Holiday"),
    (VacationType.SPECIAL_LEAVE, "Special Leave"),
    (VacationType.UNPAID_LEAVE, "Unpaid Leave"),
    (VacationType.CARRY_OVER, "Carry-Over"),
]


class VacationRecordDialog(tk.Toplevel):

    def __init__(
        self,
        parent,
        controller: VacationController,
        model: VacationModel,
        record: Optional[VacationRecord] = None,
        **_kwargs,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._model = model
        self._record = record

        editing = record is not None
        self.title("Edit Vacation Record" if editing else "Add Vacation Record")
        self.resizable(False, False)
        self.minsize(400, 320)
        self.transient(parent)
        self.grab_set()

        self._build_ui()
        self._populate(record)

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

        # ── Hours ─────────────────────────────────────────────────────────────
        hours_row = ttk.Frame(outer)
        hours_row.pack(fill="x", pady=(0, 6))
        ttk.Label(hours_row, text="Hours:", width=8, anchor="e").pack(side="left")
        self._var_hours = tk.StringVar(value="8.0")
        self._spn_hours = ttk.Spinbox(
            hours_row, textvariable=self._var_hours,
            from_=0.5, to=24.0, increment=0.5, width=8,
            format="%.1f",
        )
        self._spn_hours.pack(side="left", padx=(4, 0))

        # ── Vacation Type ─────────────────────────────────────────────────────
        type_lbl_row = ttk.Frame(outer)
        type_lbl_row.pack(fill="x", pady=(0, 2))
        ttk.Label(type_lbl_row, text="Type:", width=8, anchor="e").pack(side="left")

        self._var_vtype = tk.StringVar(value=str(VacationType.ANNUAL_LEAVE))
        for vt, label in _VTYPE_OPTIONS:
            ttk.Radiobutton(
                type_lbl_row,
                text=label,
                variable=self._var_vtype,
                value=str(vt),
            ).pack(side="left", padx=(4, 0))

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

    # ─────────────────────────── Data Population ────────────────────────────

    def _populate(self, record: Optional[VacationRecord]) -> None:
        if record is None:
            self._set_date(date.today())
            self._var_hours.set("8.0")
            self._var_vtype.set(str(VacationType.ANNUAL_LEAVE))
            self._var_note.set("")
        else:
            self._set_date(record.date)
            self._var_hours.set(f"{record.hours:.1f}")
            self._var_vtype.set(str(record.vtype))
            self._var_note.set(record.note or "")

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

        vt_val = self._var_vtype.get()
        try:
            vtype = VacationType(vt_val)
        except ValueError:
            field_errors.append(f"Invalid vacation type: {vt_val!r}")
            vtype = VacationType.ANNUAL_LEAVE

        if field_errors:
            self._lbl_error.config(text="\n".join(field_errors))
            return

        note_s = self._var_note.get().strip()
        record = VacationRecord(
            id=self._record.id if self._record is not None else None,
            date=rec_date,
            hours=hours,
            vtype=vtype,
            note=note_s or None,
        )

        result = self._controller.save_record(record, confirm_over_balance=confirm_over_balance)
        if result.ok:
            self.destroy()
        elif "OVER_BALANCE_WARNING" in result.errors:
            if messagebox.askyesno(
                "Balance Exceeded",
                "This exceeds your remaining vacation balance.\nSave anyway?",
                parent=self,
            ):
                self._on_save(confirm_over_balance=True)
        else:
            self._lbl_error.config(text="\n".join(result.errors))
