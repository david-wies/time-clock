"""Help viewer — opens documentation in the default browser."""
import os
import webbrowser
from pathlib import Path
from tkinter import messagebox


def open_help() -> None:
    """Opens the help documentation in the default web browser."""
    help_path = Path(__file__).parent.parent / 'help' / 'index.html'
    if help_path.exists():
        webbrowser.open(help_path.as_uri())
    else:
        # Fallback: try absolute path
        webbrowser.open(f'file://{help_path.resolve()}')
    return


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
