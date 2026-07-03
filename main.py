"""Entry point: wires Database → Models → Controllers → Views."""

import tkinter as tk
from datetime import date
from tkinter import messagebox

from controllers.miliuim_controller import MiliuimController
from controllers.sickness_controller import SicknessController
from controllers.time_clock_controller import TimeClockController
from controllers.vacation_controller import VacationController
from core.events import EventBus
from db.database import Database
from models.miliuim_model import MiliuimModel
from models.sickness_model import SicknessModel
from models.time_clock_model import TimeClockModel
from models.vacation_model import VacationModel
from settings import SettingsManager
from theme.style import apply_theme
from views.main_window import MainWindow
from views.miliuim_tab import MiliuimTab
from views.sickness_tab import SicknessTab
from views.time_clock_tab import TimeClockTab
from views.tray import SystemTray
from views.vacation_tab import VacationTab


def main() -> None:
    db = Database()
    settings = SettingsManager(db)
    bus = EventBus()

    time_model = TimeClockModel(db, bus)
    vacation_model = VacationModel(db, bus)
    sickness_model = SicknessModel(db, bus)
    miliuim_model = MiliuimModel(db, bus)

    time_ctrl = TimeClockController(time_model, settings)
    vacation_ctrl = VacationController(vacation_model)
    sickness_ctrl = SicknessController(sickness_model)
    miliuim_ctrl = MiliuimController(miliuim_model)

    root = tk.Tk()
    root.title("Time Clock")

    mode = settings.get("theme") or "light"
    apply_theme(root, mode)

    window = MainWindow(
        root,
        bus,
        settings=settings,
        model_tc=time_model,
        model_vacation=vacation_model,
        model_sickness=sickness_model,
        model_miliuim=miliuim_model,
    )

    tab = TimeClockTab(
        window.time_clock_frame,
        controller=time_ctrl,
        model=time_model,
        settings=settings,
        bus=bus,
        root=root,
    )

    VacationTab(
        window.vacation_frame,
        controller=vacation_ctrl,
        model=vacation_model,
        settings=settings,
        bus=bus,
        root=root,
    )

    SicknessTab(
        window.sickness_frame,
        controller=sickness_ctrl,
        model=sickness_model,
        settings=settings,
        bus=bus,
        root=root,
    )

    MiliuimTab(
        window.miliuim_frame,
        controller=miliuim_ctrl,
        model=miliuim_model,
        settings=settings,
        bus=bus,
        root=root,
    )

    _boot_checks(root, time_model, time_ctrl, tab)

    tray = SystemTray(root, time_ctrl, time_model, settings, bus)
    tray.start()

    root.mainloop()


def _boot_checks(
    root: tk.Tk, model: TimeClockModel, ctrl: TimeClockController, tab: TimeClockTab
) -> None:
    """Warn about open records from a previous day on startup."""
    open_records = model.get_open_records()
    today = date.today()
    stale = [r for r in open_records if r.date < today]
    if stale:
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
                result = ctrl.delete_record(r.id)
                if not result.ok:
                    messagebox.showwarning(
                        "Delete Failed",
                        f"Could not delete record from {r.date.isoformat()}: "
                        + "; ".join(result.errors),
                    )


if __name__ == "__main__":
    main()
