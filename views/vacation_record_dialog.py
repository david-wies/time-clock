"""Add / Edit Vacation Record dialog."""

from __future__ import annotations

import logging
import sqlite3
import tkinter as tk
from datetime import date
from tkinter import messagebox, ttk

from controllers.vacation_controller import VacationController
from domain.enums import VacationType, WarningCode
from domain.types import VacationRecord
from models.vacation_model import VacationModel
from views.date_picker import make_date_picker
from views.dialog_common import setup_modal_window, validate_note_length

logger = logging.getLogger(__name__)

_VTYPE_OPTIONS: list[tuple[VacationType, str]] = [
    (VacationType.ANNUAL_LEAVE, "Annual Leave"),
    (VacationType.PUBLIC_HOLIDAY, "Public Holiday"),
    (VacationType.SPECIAL_LEAVE, "Special Leave"),
    (VacationType.UNPAID_LEAVE, "Unpaid Leave"),
    # Carry-Over deliberately excluded: it can only be recorded via
    # VacationController.add_carry_over() (see carry_over_dialog.py), never
    # through this Add/Edit dialog. VacationController.save_record() has an
    # explicit type check that rejects VacationType.CARRY_OVER, so selecting
    # it here would type-check fine but always fail on save.
]


class VacationRecordDialog(tk.Toplevel):
    """Modal Toplevel dialog for adding or editing a vacation record."""

    def __init__(
        self,
        parent,
        controller: VacationController,
        model: VacationModel,
        record: VacationRecord | None = None,
        **_kwargs,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._model = model
        self._record = record
        # Set by _on_save() when the save hit the RECORD_NOT_FOUND
        # stale-record race. The dialog is modal, so the opening tab reads
        # this after wait_window() returns to trigger a data reload.
        self.record_vanished = False

        editing = record is not None
        setup_modal_window(
            self,
            parent,
            "Edit Vacation Record" if editing else "Add Vacation Record",
            minsize=(400, 320),
        )

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

        self._date_widget, self._get_date, self._set_date = make_date_picker(date_row)
        self._date_widget.pack(side="left", padx=(4, 0))
        self._date_widget.bind(
            "<<DateEntrySelected>>", lambda _e: self._update_hours_cap()
        )

        # ── Hours ─────────────────────────────────────────────────────────────
        hours_row = ttk.Frame(outer)
        hours_row.pack(fill="x", pady=(0, 6))
        ttk.Label(hours_row, text="Hours:", width=8, anchor="e").pack(side="left")
        self._var_hours = tk.StringVar(value="8.0")
        self._spn_hours = ttk.Spinbox(
            hours_row,
            textvariable=self._var_hours,
            from_=0.5,
            to=24.0,
            increment=0.5,
            width=8,
            format="%.1f",
        )
        self._spn_hours.pack(side="left", padx=(4, 0))
        self._lbl_hours_hint = ttk.Label(hours_row, text="", foreground="gray")
        self._lbl_hours_hint.pack(side="left", padx=(6, 0))

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

    def _populate(self, record: VacationRecord | None) -> None:
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
        self._update_hours_cap()

    def _update_hours_cap(self) -> None:
        try:
            d = self._get_date()
        except (ValueError, IndexError) as exc:
            logger.warning("Could not read date for hours-cap lookup: %s", exc)
            return

        try:
            cap = self._model.get_daily_target_for_date(d)
        except sqlite3.Error:
            logger.exception(
                "Database error looking up the daily hours cap for %s; "
                "the max-hours hint will not update",
                d,
            )
            return

        if cap == 0.0:
            cap = 8.0
        self._spn_hours.config(to=cap)
        self._lbl_hours_hint.config(text=f"(max {cap:.1f}h for this day)")
        try:
            current = float(self._var_hours.get())
            if current > cap:
                self._var_hours.set(f"{cap:.1f}")
        except ValueError:
            pass

    # ─────────────────────────── Validation ─────────────────────────────────

    def _validate_note(self, proposed: str) -> bool:
        return validate_note_length(proposed)

    # ─────────────────────────── Save ────────────────────────────────────────

    def _on_save(self, confirm_over_balance: bool = False) -> None:
        self._lbl_error.config(text="")
        field_errors: list[str] = []

        try:
            rec_date: date | None = self._get_date()
        except (ValueError, IndexError) as exc:
            logger.warning(
                "Could not parse date %r for vacation record: %s",
                self._date_widget.get(),
                exc,
            )
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
        try:
            record = VacationRecord(
                id=self._record.id if self._record is not None else None,
                date=rec_date,
                hours=hours,
                vtype=vtype,
                note=note_s or None,
            )
        except ValueError as exc:
            self._lbl_error.config(text=str(exc))
            return

        result = self._controller.save_record(
            record, confirm_over_balance=confirm_over_balance
        )
        if result.ok:
            self.destroy()
        elif WarningCode.OVER_BALANCE.value in result.errors:
            if messagebox.askyesno(
                "Balance Exceeded",
                "This exceeds your remaining vacation balance.\nSave anyway?",
                parent=self,
            ):
                self._on_save(confirm_over_balance=True)
        elif WarningCode.RECORD_NOT_FOUND.value in result.errors:
            # Stale-record race: the record being edited was already
            # deleted elsewhere, so this save can never succeed — inform
            # the user and close (the opening tab reloads via
            # record_vanished).
            messagebox.showwarning(
                "Record No Longer Exists",
                "This record no longer exists — it may have already been "
                "deleted elsewhere. The list will refresh.",
                parent=self,
            )
            self.record_vanished = True
            self.destroy()
        else:
            self._lbl_error.config(text="\n".join(result.errors))
