"""Entry point: wires Database → Models → Controllers → Views."""

import logging
import logging.handlers
import tkinter as tk
from datetime import date
from pathlib import Path
from tkinter import messagebox

from controllers.miliuim_controller import MiliuimController
from controllers.sickness_controller import SicknessController
from controllers.time_clock_controller import TimeClockController
from controllers.vacation_controller import VacationController
from core.events import EventBus
from db.database import Database, get_app_data_dir
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

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def _configure_logging(log_dir: Path | None = None) -> None:
    """Configure the root logger so every ``logging.getLogger(__name__)``
    call site across the app (controllers, models, views, ``core.events``,
    ``settings``, etc.) is captured, with zero changes needed at those call
    sites.

    Without this, unconfigured logging falls back to Python's "handler of
    last resort", which only prints WARNING-and-above to stderr -- an
    invisible sink in a packaged, windowed (PyInstaller ``--windowed``)
    build with no console. Writes to a rotating log file alongside the
    SQLite DB in the per-OS app-data directory computed by
    :func:`db.database.get_app_data_dir` -- reusing that path resolution
    rather than inventing a second one. Rotation keeps the log bounded for
    the lifetime of an always-running system-tray app.

    :param log_dir: Overrides the log directory; defaults to
        ``get_app_data_dir()``. Exposed mainly so tests can redirect
        logging to a ``tmp_path`` without touching real app-data.
    """
    directory = log_dir if log_dir is not None else get_app_data_dir()
    handler = logging.handlers.RotatingFileHandler(
        directory / "time_clock.log",
        encoding="utf-8",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
    )
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(handler)


def main() -> None:
    _configure_logging()

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
