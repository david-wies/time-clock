"""Entry point: wires Database → Models → Controllers → Views."""

import tkinter as tk
from datetime import date

from db.database import Database
from settings import SettingsManager
from core.events import EventBus
from models.time_clock_model import TimeClockModel
from controllers.time_clock_controller import TimeClockController
from theme.style import apply_theme
from views.main_window import MainWindow
from views.time_clock_tab import TimeClockTab


def main() -> None:
    db = Database()
    settings = SettingsManager(db)
    bus = EventBus()

    time_model = TimeClockModel(db, bus)
    time_ctrl = TimeClockController(time_model, settings)

    root = tk.Tk()
    root.title("Time Clock")

    mode = settings.get("theme") or "light"
    apply_theme(root, mode)

    window = MainWindow(root, bus)

    tab = TimeClockTab(
        window.time_clock_frame,
        controller=time_ctrl,
        model=time_model,
        settings=settings,
        bus=bus,
        root=root,
    )

    _boot_checks(root, time_model, time_ctrl, tab)

    root.mainloop()


def _boot_checks(root: tk.Tk, model: TimeClockModel, ctrl: TimeClockController, tab: TimeClockTab) -> None:
    """Warn about open records from a previous day on startup."""
    open_records = model.get_open_records()
    today = date.today()
    stale = [r for r in open_records if r.date < today]
    if stale:
        from tkinter import messagebox
        names = "\n".join(
            f"  {r.date.isoformat()}  {r.start_time.strftime('%H:%M')}–open"
            for r in stale
        )
        choice = messagebox.askyesno(
            "Open Records Found",
            f"Open clock-in record(s) from a previous day were found:\n\n{names}\n\n"
            "Delete them? (No = leave open for manual review)",
            icon="warning",
        )
        if choice:
            for r in stale:
                ctrl.delete_record(r.id)


if __name__ == "__main__":
    main()
