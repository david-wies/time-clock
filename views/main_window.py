"""MainWindow: ttk.Notebook tab container with menu bar and status bar."""

import logging
from tkinter import Menu, StringVar, messagebox, ttk
from typing import Any

from core.events import Event, EventBus
from views.export_dialog import ExportDialog
from views.help_viewer import open_help, report_bug, show_about, suggest_feature
from views.report_dialog import ReportDialog
from views.settings_dialog import SettingsDialog

logger = logging.getLogger(__name__)


class MainWindow(ttk.Frame):
    """Root application window with notebook tabs, menu, and status bar."""

    def __init__(self, root, bus: EventBus, settings=None, model_tc=None,
                 model_vacation=None, model_sickness=None, model_miliuim=None) -> None:
        super().__init__(root)
        self.root = root
        self.bus = bus
        self._settings = settings
        self._model_tc = model_tc
        self._model_vacation = model_vacation
        self._model_sickness = model_sickness
        self._model_miliuim = model_miliuim
        self.status_var = StringVar(value="Ready")
        self._count_var = StringVar(value="")
        self._clock_var = StringVar(value="Idle")
        self._tab_var = StringVar(value="Time Clock")

        root.title("Time Clock")
        root.minsize(800, 600)

        # Surface handler exceptions the EventBus only logs by default, and
        # catch anything an uncaught Tk widget callback (button, combobox,
        # tree, ...) raises — otherwise both fail silently in a packaged app.
        self.bus.on_handler_error = self._on_bus_handler_error
        root.report_callback_exception = self._on_tk_callback_exception

        self._build_menu(root)
        self._build_notebook()
        self._build_statusbar()

        self.pack(fill="both", expand=True)

        self._unsubs: list = [
            self.bus.subscribe(Event.TIME_RECORDS_CHANGED, lambda **
                               _: self._set_status("Records updated")),
            self.bus.subscribe(Event.VACATION_CHANGED, lambda **
                               _: self._set_status("Vacation records updated")),
            self.bus.subscribe(Event.SICKNESS_CHANGED, lambda **
                               _: self._set_status("Sick records updated")),
            self.bus.subscribe(Event.MILIUIM_CHANGED, lambda **
                               _: self._set_status("Miliuim records updated")),
            self.bus.subscribe(Event.SETTINGS_CHANGED, lambda **
                               _: self._set_status("Settings changed")),
            self.bus.subscribe(Event.CLOCK_STATE_CHANGED,
                               self._on_clock_state_changed),
        ]

        root.bind("<Destroy>", self._on_destroy)
        root.bind_all("<F1>", lambda _: open_help())
        root.bind_all("<Control-s>", lambda _: self._open_settings())

        self._set_status("Ready — Double-click record to edit")

    def _build_menu(self, root) -> None:
        menubar = Menu(root)

        file_menu = Menu(menubar, tearoff=0)
        file_menu.add_command(label="Export Time Records",
                              command=lambda: self._open_export("time"))
        file_menu.add_command(label="Export Vacation",
                              command=lambda: self._open_export("vacation"))
        file_menu.add_command(label="Export Sickness",
                              command=lambda: self._open_export("sickness"))
        file_menu.add_separator()
        file_menu.add_command(label="Reports", command=self._open_report)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=root.quit)
        menubar.add_cascade(label="File", menu=file_menu)

        settings_menu = Menu(menubar, tearoff=0)
        settings_menu.add_command(
            label="Settings", command=self._open_settings, accelerator="Ctrl+S")
        menubar.add_cascade(label="Settings", menu=settings_menu)

        help_menu = Menu(menubar, tearoff=0)
        help_menu.add_command(label="Usage Guide", command=open_help)
        help_menu.add_command(
            label="About", command=lambda: show_about(self.root))
        help_menu.add_separator()
        help_menu.add_command(
            label="Report a Bug", command=lambda: report_bug(self.root))
        help_menu.add_command(
            label="Suggest a Feature", command=lambda: suggest_feature(self.root))
        menubar.add_cascade(label="Help", menu=help_menu)

        root.config(menu=menubar)

    def _open_settings(self) -> None:
        if not all([self._settings, self._model_tc, self._model_vacation, self._model_sickness]):
            self._set_status("Settings not available")
            return

        SettingsDialog(
            self.root,
            settings=self._settings,
            model_tc=self._model_tc,
            model_vacation=self._model_vacation,
            model_sickness=self._model_sickness,
            bus=self.bus,
        )

    def _open_export(self, tab: str = "time") -> None:
        if not all([self._model_tc, self._model_vacation, self._model_sickness]):
            self._set_status("Export not available")
            return

        ExportDialog(
            self.root,
            model_tc=self._model_tc,
            model_vacation=self._model_vacation,
            model_sickness=self._model_sickness,
            tab=tab,
        )

    def _open_report(self) -> None:
        if not all([self._settings, self._model_tc, self._model_vacation, self._model_sickness]):
            self._set_status("Reports not available")
            return

        ReportDialog(
            self.root,
            model_tc=self._model_tc,
            model_vacation=self._model_vacation,
            model_sickness=self._model_sickness,
            settings=self._settings,
            model_miliuim=self._model_miliuim,
        )

    def _build_notebook(self) -> None:
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=4, pady=4)

        self.time_clock_frame = ttk.Frame(self.notebook)
        self.vacation_frame = ttk.Frame(self.notebook)
        self.sickness_frame = ttk.Frame(self.notebook)
        self.miliuim_frame = ttk.Frame(self.notebook)

        self.notebook.add(self.time_clock_frame, text="Time Clock")
        self.notebook.add(self.vacation_frame, text="Vacation")
        self.notebook.add(self.sickness_frame, text="Sickness")
        self.notebook.add(self.miliuim_frame, text="Miliuim")

        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

    def _build_statusbar(self) -> None:
        bar = ttk.Frame(self)
        bar.pack(side="bottom", fill="x", padx=4, pady=(0, 4))
        sep = ttk.Separator(bar, orient="horizontal")
        sep.pack(fill="x")

        self.status_label = ttk.Label(bar, textvariable=self.status_var,
                                      style="StatusBar.TLabel", padding=(4, 2))
        self.status_label.pack(side="left", fill="x", expand=True)

        ttk.Separator(bar, orient="vertical").pack(
            side="left", fill="y", padx=4)
        ttk.Label(bar, textvariable=self._count_var,
                  style="StatusBar.TLabel", padding=(4, 2)).pack(side="left")

        ttk.Separator(bar, orient="vertical").pack(
            side="left", fill="y", padx=4)
        ttk.Label(bar, textvariable=self._clock_var,
                  style="StatusBar.TLabel", padding=(4, 2)).pack(side="left")

        ttk.Separator(bar, orient="vertical").pack(
            side="left", fill="y", padx=4)
        ttk.Label(bar, textvariable=self._tab_var,
                  style="StatusBar.TLabel", padding=(4, 2)).pack(side="left")

    def _set_status(self, msg: str) -> None:
        self.status_var.set(msg)

    def set_record_count(self, n: int) -> None:
        self._count_var.set(f"{n} records")

    def set_clocked_in(self, is_in: bool, since: str = "") -> None:
        if is_in:
            self._clock_var.set(
                f"Clocked in{' since ' + since if since else ''}")
        else:
            self._clock_var.set("Idle")

    def _on_tab_changed(self, _event: object = None) -> None:
        idx = self.notebook.index("current")
        names = ["Time Clock", "Vacation", "Sickness", "Miliuim"]
        self._tab_var.set(names[idx] if idx < len(names) else "")

    def _on_destroy(self, _event: object = None) -> None:
        for fn in self._unsubs:
            fn()

    def _on_clock_state_changed(self, clocked_in: bool = False, since: str = "", **_: object) -> None:
        self.set_clocked_in(clocked_in, since)

    def _on_bus_handler_error(self, message: str) -> None:
        """EventBus.on_handler_error hook: a subscriber raised. The bus has
        already logged the full traceback; let the user know something went
        wrong instead of leaving the UI silently stale."""
        messagebox.showerror(
            "Unexpected Error",
            "An internal error occurred while updating the app.\n"
            "The application will keep running, but a screen may be stale — "
            "details were written to the log.",
            parent=self.root,
        )

    def _on_tk_callback_exception(self, exc: type[BaseException], val: BaseException, tb: Any) -> None:
        """Tk.report_callback_exception override: catches exceptions raised
        inside any bound widget callback (button, combobox, tree, ...) that
        Tk would otherwise only print to stderr and silently swallow."""
        logger.error("Unhandled exception in Tk callback",
                      exc_info=(exc, val, tb))
        messagebox.showerror(
            "Unexpected Error",
            f"An unexpected error occurred:\n\n{exc.__name__}: {val}",
            parent=self.root,
        )
