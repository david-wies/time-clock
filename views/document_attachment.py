"""Shared document-attachment widget: value label + Browse/Clear buttons."""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk
from tkinter.filedialog import askopenfilename
from typing import Callable

DOCUMENT_FILETYPES = [
    ("Documents", "*.pdf *.png *.jpg *.jpeg *.bmp *.tiff *.tif *.gif"),
    ("PDF files", "*.pdf"),
    ("Image files", "*.png *.jpg *.jpeg *.bmp *.tiff *.tif *.gif"),
    ("All files", "*.*"),
]


def make_document_picker(
    parent, initial_path: str | None = None, label_width: int = 24
) -> tuple[ttk.Frame, Callable[[], str | None], Callable[[str | None], None]]:
    """Creates the document-name label plus Browse/Clear buttons, packed left-to-right
    inside a returned frame. The caller places its own "Document:" row label and packs
    the returned frame alongside it (mirroring views/date_picker.py:make_date_picker).
    Returns (frame, get_path, set_path).
    """
    frame = ttk.Frame(parent)
    var_doc_path = tk.StringVar(value="")
    lbl_doc_name = ttk.Label(
        frame, text="None", foreground="gray", width=label_width, anchor="w"
    )

    def get_path() -> str | None:
        return var_doc_path.get() or None

    def set_path(path: str | None) -> None:
        var_doc_path.set(path or "")
        if path:
            lbl_doc_name.config(text=os.path.basename(path), foreground="black")
        else:
            lbl_doc_name.config(text="None", foreground="gray")

    def browse_document() -> None:
        path = askopenfilename(
            parent=frame.winfo_toplevel(),
            title="Attach Document",
            filetypes=DOCUMENT_FILETYPES,
        )
        if path:
            set_path(path)

    def clear_document() -> None:
        set_path(None)

    lbl_doc_name.pack(side="left", padx=(4, 4))
    ttk.Button(frame, text="Browse…", command=browse_document, width=9).pack(
        side="left", padx=(0, 4)
    )
    ttk.Button(frame, text="Clear", command=clear_document, width=7).pack(side="left")

    set_path(initial_path)

    return frame, get_path, set_path
