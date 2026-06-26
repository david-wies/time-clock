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

        root.title("Time Clock")
        root.minsize(800, 600)

        self._build_menu(root)
        self._build_notebook()
        self._build_statusbar()

        self.pack(fill="both", expand=True)

        self.bus.subscribe(Event.TIME_RECORDS_CHANGED, lambda **_: self._set_status("Records updated"))
        self.bus.subscribe(Event.VACATION_CHANGED, lambda **_: self._set_status("Vacation records updated"))
        self.bus.subscribe(Event.SICKNESS_CHANGED, lambda **_: self._set_status("Sick records updated"))
        self.bus.subscribe(Event.SETTINGS_CHANGED, lambda **_: self._set_status("Settings changed"))
        self.bus.subscribe(Event.CLOCK_STATE_CHANGED, lambda **_: self._set_status("Clock state changed"))

        self._set_status("Ready — Double-click record to edit")

    def _build_menu(self, root) -> None:
        menubar = Menu(root)

        file_menu = Menu(menubar, tearoff=0)
        file_menu.add_command(label="Export Time Records", command=self._not_ready)
        file_menu.add_command(label="Export Vacation", command=self._not_ready)
        file_menu.add_command(label="Export Sickness", command=self._not_ready)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=root.quit)
        menubar.add_cascade(label="File", menu=file_menu)

        settings_menu = Menu(menubar, tearoff=0)
        settings_menu.add_command(label="Settings", command=self._not_ready, accelerator="Ctrl+S")
        menubar.add_cascade(label="Settings", menu=settings_menu)

        help_menu = Menu(menubar, tearoff=0)
        help_menu.add_command(label="Usage Guide", command=open_help)
        help_menu.add_command(label="About", command=lambda: show_about(self.root))
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

    def _build_statusbar(self) -> None:
        bar = ttk.Frame(self)
        bar.pack(side="bottom", fill="x", padx=4, pady=(0, 4))
        sep = ttk.Separator(bar, orient="horizontal")
        sep.pack(fill="x")
        self.status_label = ttk.Label(bar, textvariable=self.status_var,
                                      style="StatusBar.TLabel", padding=(4, 2))
        self.status_label.pack(side="left")

    def _set_status(self, msg: str) -> None:
        self.status_var.set(msg)

    def _not_ready(self) -> None:
        self._set_status("Not yet implemented")
