"""Shared modal-dialog window chrome for tk.Toplevel-based dialogs."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox

from domain.enums import RECORD_NOT_FOUND_MESSAGE


def close_dialog_record_vanished(dialog: tk.Toplevel) -> None:
    """Handle the RECORD_NOT_FOUND save-race in a record-edit dialog.

    The record being edited was already deleted elsewhere, so the save can
    never succeed. Warn the user, flag ``record_vanished`` so the opening
    tab's ``_after_record_dialog`` reloads to drop the phantom row, then
    close. This uses ``showwarning`` (not the ``showinfo`` of the passive
    delete/clock-out races) because the user's in-progress edits are being
    discarded."""
    messagebox.showwarning(
        "Record No Longer Exists", RECORD_NOT_FOUND_MESSAGE, parent=dialog
    )
    dialog.record_vanished = True
    dialog.destroy()


def setup_modal_window(
    dialog: tk.Toplevel,
    parent: tk.Misc,
    title: str,
    minsize: tuple[int, int],
    resizable: tuple[bool, bool] = (False, False),
) -> None:
    """Applies the standard modal-dialog chrome: title, min size, resizability,
    transient-to-parent, input grab, and Escape-to-close."""
    dialog.title(title)
    dialog.minsize(*minsize)
    dialog.resizable(*resizable)
    dialog.transient(parent)
    dialog.grab_set()
    dialog.bind("<Escape>", lambda _e: dialog.destroy())


def validate_note_length(proposed: str, max_len: int = 500) -> bool:
    """Tk entry validatecommand callback: rejects note text past `max_len`."""
    return len(proposed) <= max_len
