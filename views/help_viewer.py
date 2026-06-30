"""Help viewer — opens documentation in the default browser."""
import webbrowser
from pathlib import Path
from tkinter import messagebox


def open_help() -> None:
    """Opens the help documentation in the default web browser."""
    help_path = Path(__file__).parent.parent / 'help' / 'index.html'
    if not help_path.exists():
        messagebox.showwarning("Help Not Found", f"Help file not found:\n{help_path}")
        return
    try:
        webbrowser.open(help_path.as_uri())
    except webbrowser.Error as exc:
        messagebox.showerror("Help Error", f"Could not open help file:\n{exc}")


def show_about(parent=None) -> None:
    """Shows an About dialog using tkinter messagebox."""
    messagebox.showinfo(
        'About Time Clock',
        'Time Clock Application\n'
        'Version 1.0.0\n\n'
        'A desktop time tracking application\n'
        'for managing work hours, vacation,\n'
        'and sick leave.\n\n'
        'Built with Python & tkinter.',
        parent=parent
    )
    return
