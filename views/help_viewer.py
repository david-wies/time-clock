"""Help viewer — opens documentation in the default browser."""

import logging
import re
import tkinter as tk
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox, ttk
from urllib.parse import urlencode

from version import __version__ as _APP_VERSION

logger = logging.getLogger(__name__)

_REPO_URL = "https://github.com/david-wies/time-clock"

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_MAX_ISSUE_URL_LENGTH = 8000


@dataclass(frozen=True)
class _ReportKind:
    template: str
    field_id: str
    title: str


_KIND_CONFIG = {
    "bug": _ReportKind(
        template="bug_report.yml", field_id="description", title="Report a Bug"
    ),
    "feature": _ReportKind(
        template="feature_request.yml", field_id="problem", title="Suggest a Feature"
    ),
}


def _build_issue_url(kind: str, name: str, email: str, message: str) -> str:
    """Builds a GitHub new-issue URL prefilled from the report dialog."""
    config = _KIND_CONFIG[kind]
    params = {
        "template": config.template,
        "contact": f"{name} <{email}>",
        config.field_id: message,
    }
    if kind == "bug":
        # bug_report.yml's "Environment" field asks for OS, Python version,
        # and app version -- prefill the one part we actually know so the
        # user doesn't have to look it up, leaving OS/Python for them to
        # fill in.
        params["environment"] = f"App version: v{_APP_VERSION}\n"
    return f"{_REPO_URL}/issues/new?{urlencode(params)}"


def _show_modal(dialog, parent) -> None:
    """Centers `dialog` on `parent` (if any), makes it modal, and blocks
    until it is closed."""
    dialog.update_idletasks()
    if parent is not None:
        x = parent.winfo_rootx() + (parent.winfo_width() - dialog.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    dialog.grab_set()
    dialog.focus_set()
    dialog.bind("<Escape>", lambda e: dialog.destroy())
    dialog.wait_window()


def open_help() -> None:
    """Opens the help documentation in the default web browser."""
    help_path = Path(__file__).parent.parent / "help" / "index.html"
    if not help_path.exists():
        messagebox.showwarning("Help Not Found", f"Help file not found:\n{help_path}")
        return
    try:
        opened = webbrowser.open(help_path.as_uri())
    except (webbrowser.Error, OSError) as exc:
        messagebox.showerror("Help Error", f"Could not open help file:\n{exc}")
        return
    if not opened:
        messagebox.showerror("Help Error", "Could not open a web browser.")


def show_about(parent=None) -> None:
    """Shows an About dialog with a clickable GitHub link."""
    dialog = tk.Toplevel(parent)
    dialog.title("About Time Clock")
    dialog.resizable(False, False)

    if parent is not None:
        dialog.transient(parent)

    container = ttk.Frame(dialog, padding=20)
    container.pack(fill="both", expand=True)

    lines = [
        "Time Clock Application",
        f"Version {_APP_VERSION}",
        "",
        "A desktop time tracking application",
        "for managing work hours, vacation,",
        "sick leave, miliuim (reserve duty)",
        "date-range periods, and road time",
        "records with document attachments.",
        "",
    ]
    for line in lines:
        ttk.Label(container, text=line).pack(anchor="w")

    link = tk.Label(
        container,
        text="GitHub: github.com/david-wies/time-clock",
        fg="blue",
        cursor="hand2",
        font=("TkDefaultFont", 9, "underline"),
    )
    link.pack(anchor="w")

    def _open_github_link(_event: object) -> None:
        try:
            opened = webbrowser.open("https://github.com/david-wies/time-clock")
        except webbrowser.Error, OSError:
            logger.warning("Could not open GitHub link in browser", exc_info=True)
            return
        if not opened:
            logger.warning("Could not open a web browser for the GitHub link.")

    link.bind("<Button-1>", _open_github_link)

    ttk.Label(container, text="").pack(anchor="w")
    ttk.Label(container, text="Built with Python & tkinter.").pack(anchor="w")

    ttk.Button(container, text="OK", command=dialog.destroy).pack(pady=(15, 0))

    _show_modal(dialog, parent)


def _report_dialog(parent, kind: str) -> None:
    """Opens a modal dialog collecting name/email/message, then opens
    a prefilled GitHub issue page in the default browser."""
    dialog = tk.Toplevel(parent)
    dialog.title(_KIND_CONFIG[kind].title)
    dialog.resizable(False, False)

    if parent is not None:
        dialog.transient(parent)

    container = ttk.Frame(dialog, padding=20)
    container.pack(fill="both", expand=True)

    ttk.Label(container, text="Name").grid(row=0, column=0, sticky="w", pady=(0, 4))
    name_var = tk.StringVar()
    ttk.Entry(container, textvariable=name_var, width=40).grid(
        row=1, column=0, sticky="ew", pady=(0, 10)
    )

    ttk.Label(container, text="Email").grid(row=2, column=0, sticky="w", pady=(0, 4))
    email_var = tk.StringVar()
    ttk.Entry(container, textvariable=email_var, width=40).grid(
        row=3, column=0, sticky="ew", pady=(0, 10)
    )

    ttk.Label(container, text="Message").grid(row=4, column=0, sticky="w", pady=(0, 4))
    message_text = tk.Text(container, width=40, height=8, wrap="word")
    message_text.grid(row=5, column=0, sticky="ew", pady=(0, 10))

    def _on_submit() -> None:
        name = name_var.get().strip()
        email = email_var.get().strip()
        message = message_text.get("1.0", "end").strip()

        if not name or not email or not _EMAIL_RE.match(email) or not message:
            messagebox.showwarning(
                "Missing Information",
                "Name, a valid email, and a message are all required.",
                parent=dialog,
            )
            return

        url = _build_issue_url(kind, name, email, message)
        if len(url) > _MAX_ISSUE_URL_LENGTH:
            messagebox.showwarning(
                "Message Too Long",
                "Your message is too long to prefill in the browser. "
                "Please shorten it and try again.",
                parent=dialog,
            )
            return

        try:
            opened = webbrowser.open(url)
        except (webbrowser.Error, OSError) as exc:
            messagebox.showerror(
                "Browser Error", f"Could not open browser:\n{exc}", parent=dialog
            )
            return
        if not opened:
            messagebox.showerror(
                "Browser Error", "Could not open a web browser.", parent=dialog
            )
            return
        dialog.destroy()

    button_row = ttk.Frame(container)
    button_row.grid(row=6, column=0, sticky="e")
    ttk.Button(button_row, text="Cancel", command=dialog.destroy).pack(
        side="right", padx=(6, 0)
    )
    ttk.Button(button_row, text="Submit", command=_on_submit).pack(side="right")

    _show_modal(dialog, parent)


def report_bug(parent=None) -> None:
    """Opens the bug-report dialog."""
    _report_dialog(parent, "bug")


def suggest_feature(parent=None) -> None:
    """Opens the feature-request dialog."""
    _report_dialog(parent, "feature")
