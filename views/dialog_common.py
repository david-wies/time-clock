"""Shared modal-dialog window chrome for tk.Toplevel-based dialogs."""

from __future__ import annotations

import tkinter as tk


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
