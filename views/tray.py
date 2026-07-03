"""System tray icon with quick clock-in/out actions (§21.4)."""

import logging
import threading
import tkinter as tk
import tkinter.messagebox
from datetime import date
from pathlib import Path

import pystray
from PIL import Image, ImageDraw

from controllers.time_clock_controller import TimeClockController
from core.events import Event, EventBus
from domain.enums import WarningCode
from models.time_clock_model import TimeClockModel
from settings import SettingsManager

logger = logging.getLogger(__name__)

_ICON_SIZE = 64
_BADGE_COLOR = (22, 163, 74, 255)  # success green
_PNG_PATH = Path(__file__).parent.parent / "resources" / "time-clock.png"


def _load_base_icon() -> Image.Image:
    return (
        Image.open(_PNG_PATH)
        .convert("RGBA")
        .resize((_ICON_SIZE, _ICON_SIZE), Image.LANCZOS)
    )


def _make_icon(clocked_in: bool, base: Image.Image) -> Image.Image:
    img = base.copy()
    if clocked_in:
        draw = ImageDraw.Draw(img)
        r = _ICON_SIZE // 5
        x0, y0 = _ICON_SIZE - r * 2 - 2, _ICON_SIZE - r * 2 - 2
        draw.ellipse([x0, y0, x0 + r * 2, y0 + r * 2], fill=_BADGE_COLOR)
    return img


class SystemTray:
    """Manages the pystray system-tray icon.

    All controller/UI calls are marshalled to the tkinter main thread via
    root.after(0, fn) — never call controllers or touch tkinter from the
    pystray thread directly (§21.4 thread-safety requirement).
    """

    def __init__(
        self,
        root: tk.Tk,
        controller: TimeClockController,
        model: TimeClockModel,
        settings: SettingsManager,
        bus: EventBus,
    ) -> None:
        self._root = root
        self._controller = controller
        self._model = model
        self._settings = settings
        self._icon: pystray.Icon | None = None
        # Cached on the Tk main thread only -- pystray evaluates
        # MenuItem(enabled=...) predicates lazily on its own background
        # icon-rendering thread on backends that render menus (Windows,
        # Linux GTK/AppIndicator), so those predicates must never query
        # self._model (a shared, single-thread-affine sqlite3.Connection)
        # directly. Refreshed in _on_records_changed(), which does run on
        # the main thread.
        self._clocked_in_cache: bool = False
        try:
            self._base_icon: Image.Image = _load_base_icon()
        except (FileNotFoundError, OSError):
            logger.warning("icon file not found at %r; using fallback icon.", _PNG_PATH)
            self._base_icon = Image.new(
                "RGBA", (_ICON_SIZE, _ICON_SIZE), (80, 120, 200, 255)
            )
        self._unsubs = [
            bus.subscribe(Event.CLOCK_STATE_CHANGED, self._on_records_changed),
            bus.subscribe(Event.TIME_RECORDS_CHANGED, self._on_records_changed),
        ]

    # ─────────────────────── Public API ────────────────────────────────────

    def start(self) -> None:
        """Create and start the tray icon in a daemon thread."""
        self._clocked_in_cache = self._is_clocked_in()
        self._icon = pystray.Icon(
            "time-clock",
            self._current_icon_image(),
            title=self._current_title(),
            menu=self._build_menu(),
        )
        threading.Thread(target=self._icon.run, daemon=True).start()
        self._root.protocol("WM_DELETE_WINDOW", self._on_window_close)

    def stop(self) -> None:
        """Stop the tray icon and unsubscribe from the event bus."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._icon:
            self._icon.stop()
            self._icon = None

    # ─────────────────────── Icon helpers ──────────────────────────────────

    def _is_clocked_in(self) -> bool:
        return bool(self._model.get_open_records_for_date(date.today()))

    def _current_icon_image(self) -> Image.Image:
        return _make_icon(self._is_clocked_in(), self._base_icon)

    def _current_title(self) -> str:
        return "Time Clock — Clocked In" if self._is_clocked_in() else "Time Clock"

    def _build_menu(self) -> pystray.Menu:
        return pystray.Menu(
            pystray.MenuItem(
                "Clock In",
                self._tray_clock_in,
                enabled=lambda _: not self._clocked_in_cache,
            ),
            pystray.MenuItem(
                "Clock Out",
                self._tray_clock_out,
                enabled=lambda _: self._clocked_in_cache,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open", self._tray_open, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._tray_quit),
        )

    # ─────────────────────── Event handler ─────────────────────────────────

    def _on_records_changed(self, **_) -> None:
        """Called from tkinter main thread via synchronous EventBus."""
        self._clocked_in_cache = self._is_clocked_in()
        if not self._icon:
            return
        self._icon.icon = self._current_icon_image()
        self._icon.title = self._current_title()

    # ─────────────────── Tray callbacks (pystray thread) ───────────────────

    def _tray_clock_in(self, icon, item) -> None:
        self._root.after(0, self._do_clock_in)

    def _tray_clock_out(self, icon, item) -> None:
        self._root.after(0, self._do_clock_out)

    def _tray_open(self, icon, item) -> None:
        self._root.after(0, self._do_open)

    def _tray_quit(self, icon, item) -> None:
        self._root.after(0, self._do_quit)

    # ─────────────────── Main-thread actions ───────────────────────────────

    def _do_clock_in(self) -> None:
        result = self._controller.clock_in()
        if not result.ok and result.errors != [WarningCode.OPEN_RECORD_EXISTS.value]:
            errors = result.errors
            self._root.after(
                0,
                lambda: tk.messagebox.showerror("Clock In Failed", "\n".join(errors)),
            )

    def _do_clock_out(self) -> None:
        result = self._controller.clock_out()
        if not result.ok:
            if result.errors == [WarningCode.MULTIPLE_OPEN_RECORDS.value]:
                self._root.after(
                    0,
                    lambda: tk.messagebox.showinfo(
                        "Multiple Open Records",
                        "Multiple open records exist for today.\n"
                        "Open the main window to choose which one to clock out.",
                    ),
                )
                return
            errors = result.errors
            self._root.after(
                0,
                lambda: tk.messagebox.showerror("Clock Out Failed", "\n".join(errors)),
            )

    def _do_open(self) -> None:
        self._root.deiconify()
        self._root.lift()
        self._root.focus_force()

    def _do_quit(self) -> None:
        self.stop()
        self._root.destroy()

    def _on_window_close(self) -> None:
        if self._settings.get("minimize_to_tray"):
            self._root.withdraw()
        else:
            self.stop()
            self._root.destroy()
