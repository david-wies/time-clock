"""Add / Edit Miliuim Record dialog."""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk, messagebox
from tkinter.filedialog import askopenfilename
from datetime import date
from typing import Optional

from controllers.miliuim_controller import MiliuimController
from models.miliuim_model import MiliuimModel
from domain.types import MiliuimRecord
from views.date_picker import make_date_picker


class MiliuimRecordDialog(tk.Toplevel):

    def __init__(
        self,
        parent,
        controller: MiliuimController,
        model: MiliuimModel,
        record: Optional[MiliuimRecord] = None,
        **_kwargs,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._model = model
        self._record = record

        editing = record is not None
        self.title("Edit Miliuim Period" if editing else "Add Miliuim Period")
        self.resizable(False, False)
        self.minsize(420, 280)
        self.transient(parent)
        self.grab_set()

        self._build_ui()
        self._populate(record)

        self.wait_window(self)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=(16, 12, 16, 8))
        outer.pack(fill="both", expand=True)

        # ── Start Date ────────────────────────────────────────────────────────
        start_row = ttk.Frame(outer)
        start_row.pack(fill="x", pady=(0, 6))
        ttk.Label(start_row, text="Start date:",
                  width=11, anchor="e").pack(side="left")
        self._date_widget, self._get_date, self._set_date = make_date_picker(
            start_row)
        self._date_widget.pack(side="left", padx=(4, 0))

        # ── End Date ──────────────────────────────────────────────────────────
        end_row = ttk.Frame(outer)
        end_row.pack(fill="x", pady=(0, 6))
        ttk.Label(end_row, text="End date:", width=11,
                  anchor="e").pack(side="left")
        self._end_date_widget, self._get_end_date, self._set_end_date = make_date_picker(
            end_row)
        self._end_date_widget.pack(side="left", padx=(4, 0))

        # ── Note ──────────────────────────────────────────────────────────────
        note_row = ttk.Frame(outer)
        note_row.pack(fill="x", pady=(0, 6))
        ttk.Label(note_row, text="Note:", width=11,
                  anchor="e").pack(side="left")
        vcmd = (self.register(self._validate_note), "%P")
        self._var_note = tk.StringVar()
        ttk.Entry(
            note_row, textvariable=self._var_note, width=36,
            validate="key", validatecommand=vcmd,
        ).pack(side="left", padx=(4, 0), fill="x", expand=True)

        # ── Document ──────────────────────────────────────────────────────────
        doc_row = ttk.Frame(outer)
        doc_row.pack(fill="x", pady=(0, 6))
        ttk.Label(doc_row, text="Document:", width=11,
                  anchor="e").pack(side="left")
        self._var_doc_path = tk.StringVar(value="")
        self._lbl_doc_name = ttk.Label(
            doc_row, text="None", foreground="gray", width=24, anchor="w")
        self._lbl_doc_name.pack(side="left", padx=(4, 4))
        ttk.Button(doc_row, text="Browse…", command=self._browse_document,
                   width=9).pack(side="left", padx=(0, 4))
        ttk.Button(doc_row, text="Clear",
                   command=self._clear_document, width=7).pack(side="left")

        # ── Error label ───────────────────────────────────────────────────────
        self._lbl_error = ttk.Label(
            outer, text="", foreground="red", wraplength=390, justify="left"
        )
        self._lbl_error.pack(fill="x", pady=(0, 4))

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_row = ttk.Frame(outer)
        btn_row.pack(fill="x", pady=(4, 0))
        ttk.Button(btn_row, text="Cancel", command=self.destroy).pack(
            side="right", padx=(6, 0))
        ttk.Button(btn_row, text="Save",
                   command=self._on_save).pack(side="right")

    def _populate(self, record: Optional[MiliuimRecord]) -> None:
        today = date.today()
        if record is None:
            self._set_date(today)
            self._set_end_date(today)
            self._var_note.set("")
        else:
            self._set_date(record.start_date)
            self._set_end_date(record.end_date)
            self._var_note.set(record.note or "")
        doc = record.document_path if record is not None else None
        self._set_doc_path(doc)

    def _set_doc_path(self, path: Optional[str]) -> None:
        self._var_doc_path.set(path or "")
        if path:
            self._lbl_doc_name.config(
                text=os.path.basename(path), foreground="black")
        else:
            self._lbl_doc_name.config(text="None", foreground="gray")

    def _browse_document(self) -> None:
        path = askopenfilename(
            parent=self,
            title="Attach Document",
            filetypes=[
                ("Documents", "*.pdf *.png *.jpg *.jpeg *.bmp *.tiff *.tif *.gif"),
                ("PDF files", "*.pdf"),
                ("Image files", "*.png *.jpg *.jpeg *.bmp *.tiff *.tif *.gif"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self._set_doc_path(path)

    def _clear_document(self) -> None:
        self._set_doc_path(None)

    def _validate_note(self, proposed: str) -> bool:
        return len(proposed) <= 500

    def _on_save(self) -> None:
        self._lbl_error.config(text="")
        field_errors: list[str] = []

        try:
            start_date: Optional[date] = self._get_date()
        except Exception:
            field_errors.append("Invalid start date.")
            start_date = None

        try:
            end_date: Optional[date] = self._get_end_date()
        except Exception:
            field_errors.append("Invalid end date.")
            end_date = None

        if field_errors:
            self._lbl_error.config(text="\n".join(field_errors))
            return

        note_s = self._var_note.get().strip() or None

        record = MiliuimRecord(
            id=self._record.id if self._record is not None else None,
            start_date=start_date,
            end_date=end_date,
            note=note_s,
            document_path=self._var_doc_path.get() or None,
        )
        result = self._controller.save_record(record)

        if result.ok:
            self.destroy()
        else:
            self._lbl_error.config(text="\n".join(result.errors))
