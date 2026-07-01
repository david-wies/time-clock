"""Help viewer — opens documentation in the default browser."""
import webbrowser
from pathlib import Path
from tkinter import messagebox
import tkinter as tk
from tkinter import ttk
from urllib.parse import urlencode


_REPO_URL = 'https://github.com/david-wies/time-clock'

_TEMPLATE_BY_KIND = {
    'bug': 'bug_report.yml',
    'feature': 'feature_request.yml',
}

_FIELD_ID_BY_KIND = {
    'bug': 'description',
    'feature': 'problem',
}


def _build_issue_url(kind: str, name: str, email: str, message: str) -> str:
    """Builds a GitHub new-issue URL prefilled from the report dialog."""
    template = _TEMPLATE_BY_KIND[kind]
    field_id = _FIELD_ID_BY_KIND[kind]
    params = {
        'template': template,
        'contact': f'{name} <{email}>',
        field_id: message,
    }
    return f'{_REPO_URL}/issues/new?{urlencode(params)}'


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
    """Shows an About dialog with a clickable GitHub link."""
    dialog = tk.Toplevel(parent)
    dialog.title('About Time Clock')
    dialog.resizable(False, False)

    if parent is not None:
        dialog.transient(parent)

    container = ttk.Frame(dialog, padding=20)
    container.pack(fill='both', expand=True)

    lines = [
        'Time Clock Application',
        'Version 1.1.0',
        '',
        'A desktop time tracking application',
        'for managing work hours, vacation,',
        'sick leave, miliuim (reserve duty)',
        'date-range periods, and road time',
        'records with document attachments.',
        '',
    ]
    for line in lines:
        ttk.Label(container, text=line).pack(anchor='w')

    link = tk.Label(
        container,
        text='GitHub: github.com/david-wies/time-clock',
        fg='blue',
        cursor='hand2',
        font=('TkDefaultFont', 9, 'underline'),
    )
    link.pack(anchor='w')
    link.bind(
        '<Button-1>',
        lambda _event: webbrowser.open('https://github.com/david-wies/time-clock')
    )

    ttk.Label(container, text='').pack(anchor='w')
    ttk.Label(container, text='Built with Python & tkinter.').pack(anchor='w')

    ttk.Button(container, text='OK', command=dialog.destroy).pack(pady=(15, 0))

    dialog.update_idletasks()
    if parent is not None:
        x = parent.winfo_rootx() + (parent.winfo_width() - dialog.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f'+{max(x, 0)}+{max(y, 0)}')

    dialog.grab_set()
    dialog.focus_set()
    dialog.bind("<Escape>", lambda e: dialog.destroy())
    dialog.wait_window()
    return
