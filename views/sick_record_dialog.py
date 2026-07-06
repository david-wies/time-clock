"""Add / Edit Sick Record dialog."""

from __future__ import annotations

import logging
import tkinter as tk
from datetime import date
from tkinter import messagebox, ttk

from controllers.sickness_controller import SicknessController
from domain.enums import WarningCode
from domain.types import SicknessRecord
from models.sickness_model import SicknessModel
from views.date_picker import make_date_picker
from views.dialog_common import setup_modal_window
from views.document_attachment import make_document_picker

logger = logging.getLogger(__name__)


class SickRecordDialog(tk.Toplevel):
    """Modal Toplevel dialog for adding or editing a sickness record."""

    def __init__(
        self,
        parent,
        controller: SicknessController,
        model: SicknessModel,
        record: SicknessRecord | None = None,
        **_kwargs,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._model = model
        self._record = record

        editing = record is not None
        setup_modal_window(
            self,
            parent,
            "Edit Sick Record" if editing else "Add Sick Record",
            minsize=(400, 300),
        )

        self._build_ui(editing)
        self._populate(record)

        self.wait_window(self)

    # ─────────────────────────── UI Construction ────────────────────────────

    def _build_ui(self, editing: bool) -> None:
        outer = ttk.Frame(self, padding=(16, 12, 16, 8))
        outer.pack(fill="both", expand=True)

        # ── Date ──────────────────────────────────────────────────────────────
        date_row = ttk.Frame(outer)
        date_row.pack(fill="x", pady=(0, 6))
        ttk.Label(date_row, text="Date:", width=10, anchor="e").pack(side="left")

        self._date_widget, self._get_date, self._set_date = make_date_picker(date_row)
        self._date_widget.pack(side="left", padx=(4, 0))

        # ── Multi-day checkbox (hidden in edit mode) ───────────────────────────
        self._var_multiday = tk.BooleanVar(value=False)
        if not editing:
            self._chk_multiday = ttk.Checkbutton(
                outer,
                text="Multi-day range",
                variable=self._var_multiday,
                command=self._on_multiday_toggled,
            )
            self._chk_multiday.pack(anchor="w", pady=(0, 4))

        # ── End date row (revealed when multi-day is checked) ─────────────────
        self._frm_end_date = ttk.Frame(outer)
        ttk.Label(self._frm_end_date, text="End date:", width=10, anchor="e").pack(
            side="left"
        )
        self._end_date_widget, self._get_end_date, self._set_end_date = (
            make_date_picker(self._frm_end_date)
        )
        self._end_date_widget.pack(side="left", padx=(4, 0))
        # Pack it into the layout immediately so its position is fixed, then hide it.
        self._frm_end_date.pack(fill="x", pady=(0, 6))
        self._frm_end_date.pack_forget()

        # ── Hours ──────────────────────────────────────────────────────────────
        self._hours_row = ttk.Frame(outer)
        hours_row = self._hours_row
        hours_row.pack(fill="x", pady=(0, 6))
        ttk.Label(hours_row, text="Hours:", width=10, anchor="e").pack(side="left")
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

        # ── Note ──────────────────────────────────────────────────────────────
        note_row = ttk.Frame(outer)
        note_row.pack(fill="x", pady=(0, 6))
        ttk.Label(note_row, text="Note:", width=10, anchor="e").pack(side="left")
        vcmd = (self.register(self._validate_note), "%P")
        self._var_note = tk.StringVar()
        ttk.Entry(
            note_row,
            textvariable=self._var_note,
            width=36,
            validate="key",
            validatecommand=vcmd,
        ).pack(side="left", padx=(4, 0), fill="x", expand=True)

        # ── Document ──────────────────────────────────────────────────────────
        doc_row = ttk.Frame(outer)
        doc_row.pack(fill="x", pady=(0, 6))
        ttk.Label(doc_row, text="Document:", width=10, anchor="e").pack(side="left")
        self._doc_widget, self._get_doc_path, self._set_doc_path = make_document_picker(
            doc_row
        )
        self._doc_widget.pack(side="left", padx=(4, 0))

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

    # ─────────────────────────── Multi-day Toggle ────────────────────────────

    def _on_multiday_toggled(self) -> None:
        if self._var_multiday.get():
            self._frm_end_date.pack(fill="x", pady=(0, 6), before=self._hours_row)
        else:
            self._frm_end_date.pack_forget()

    # ─────────────────────────── Data Population ────────────────────────────

    def _populate(self, record: SicknessRecord | None) -> None:
        if record is None:
            self._set_date(date.today())
            self._set_end_date(date.today())
            self._var_hours.set("8.0")
            self._var_note.set("")
        else:
            self._set_date(record.date)
            self._set_end_date(record.date)
            self._var_hours.set(f"{record.hours:.1f}")
            self._var_note.set(record.note or "")
        doc = record.document_path if record is not None else None
        self._set_doc_path(doc)

    # ─────────────────────────── Validation ─────────────────────────────────

    def _validate_note(self, proposed: str) -> bool:
        return len(proposed) <= 500

    # ─────────────────────────── Save ────────────────────────────────────────

    def _on_save(self, confirm_over_balance: bool = False) -> None:
        self._lbl_error.config(text="")
        field_errors: list[str] = []

        try:
            start_date: date | None = self._get_date()
        except (ValueError, IndexError) as exc:
            logger.warning(
                "Could not parse start date %r for sick record: %s",
                self._date_widget.get(),
                exc,
            )
            field_errors.append("Invalid date.")
            start_date = None

        try:
            hours = float(self._var_hours.get())
        except ValueError:
            field_errors.append("Hours must be a number between 0.5 and 24.")
            hours = 0.0

        if field_errors:
            self._lbl_error.config(text="\n".join(field_errors))
            return

        # field_errors is empty here, so the except branch above (the only
        # place that assigns None) was never taken.
        if start_date is None:
            return

        note_s = self._var_note.get().strip()
        note = note_s or None

        multiday = self._var_multiday.get() if hasattr(self, "_var_multiday") else False

        if multiday:
            try:
                end_date = self._get_end_date()
            except (ValueError, IndexError) as exc:
                logger.warning(
                    "Could not parse end date %r for sick record: %s",
                    self._end_date_widget.get(),
                    exc,
                )
                self._lbl_error.config(text="Invalid end date.")
                return
            result = self._controller.save_range(
                start_date,
                end_date,
                hours,
                note,
                confirm_over_balance=confirm_over_balance,
                document_path=self._get_doc_path(),
            )
        else:
            try:
                record = SicknessRecord(
                    id=self._record.id if self._record is not None else None,
                    date=start_date,
                    hours=hours,
                    note=note,
                    document_path=self._get_doc_path(),
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
                "This exceeds your remaining sick hour balance.\nSave anyway?",
                parent=self,
            ):
                self._on_save(confirm_over_balance=True)
        else:
            self._lbl_error.config(text="\n".join(result.errors))
