"""MainWindow: ttk.Notebook tab container with menu bar and status bar."""

from tkinter import ttk, Menu, StringVar
from typing import Optional
from core.events import EventBus, Event
from theme.style import apply_theme
from views.help_viewer import open_help, show_about


class MainWindow(ttk.Frame):
    """Root application window with notebook tabs, menu, and status bar."""

    def __init__(self, root, bus: EventBus) -> None:
        super().__init__(root)
        self.root = root
        self.bus = bus
        self.status_var = StringVar(value="Ready")
        self._count_var = StringVar(value="")
        self._clock_var = StringVar(value="Idle")
        self._tab_var = StringVar(value="Time Clock")

        root.title("Time Clock")
        root.minsize(800, 600)

        self._build_menu(root)
        self._build_notebook()
        self._build_statusbar()

        self.pack(fill="both", expand=True)

        self.bus.subscribe(Event.TIME_RECORDS_CHANGED, lambda **
                           _: self._set_status("Records updated"))
        self.bus.subscribe(Event.VACATION_CHANGED, lambda **
                           _: self._set_status("Vacation records updated"))
        self.bus.subscribe(Event.SICKNESS_CHANGED, lambda **
                           _: self._set_status("Sick records updated"))
        self.bus.subscribe(Event.SETTINGS_CHANGED, lambda **
                           _: self._set_status("Settings changed"))
        self.bus.subscribe(Event.CLOCK_STATE_CHANGED,
                           self._on_clock_state_changed)

        root.bind_all("<F1>", lambda _: open_help())
        root.bind_all("<Control-s>", lambda _: self._not_ready())

        self._set_status("Ready — Double-click record to edit")

    def _build_menu(self, root) -> None:
        menubar = Menu(root)

        file_menu = Menu(menubar, tearoff=0)
        file_menu.add_command(label="Export Time Records",
                              command=self._not_ready)
        file_menu.add_command(label="Export Vacation", command=self._not_ready)
        file_menu.add_command(label="Export Sickness", command=self._not_ready)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=root.quit)
        menubar.add_cascade(label="File", menu=file_menu)

        settings_menu = Menu(menubar, tearoff=0)
        settings_menu.add_command(
            label="Settings", command=self._not_ready, accelerator="Ctrl+S")
        menubar.add_cascade(label="Settings", menu=settings_menu)

        help_menu = Menu(menubar, tearoff=0)
        help_menu.add_command(label="Usage Guide", command=open_help)
        help_menu.add_command(
            label="About", command=lambda: show_about(self.root))
        menubar.add_cascade(label="Help", menu=help_menu)

        root.config(menu=menubar)

    def _build_notebook(self) -> None:
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=4, pady=4)

        self.time_clock_frame = ttk.Frame(self.notebook)
        self.vacation_frame = ttk.Frame(self.notebook)
        self.sickness_frame = ttk.Frame(self.notebook)

        self.notebook.add(self.time_clock_frame, text="Time Clock")
        self.notebook.add(self.vacation_frame, text="Vacation")
        self.notebook.add(self.sickness_frame, text="Sickness")

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
        names = ["Time Clock", "Vacation", "Sickness"]
        self._tab_var.set(names[idx] if idx < len(names) else "")

    def _on_clock_state_changed(self, clocked_in: bool = False, since: str = "", **_: object) -> None:
        self.set_clocked_in(clocked_in, since)

    def _not_ready(self) -> None:
        self._set_status("Not yet implemented")
