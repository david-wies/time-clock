"""Semantic ttk style system with graceful sv-ttk fallback."""

from enum import StrEnum
from tkinter import ttk

import sv_ttk

__all__ = ["ThemeMode", "COLORS", "resolve_theme_mode", "apply_theme"]


class ThemeMode(StrEnum):
    """Selectable ttk theme mode: light, dark, or system-following."""

    LIGHT = "light"
    DARK = "dark"
    SYSTEM = "system"


COLORS = {
    ThemeMode.LIGHT: {
        "bg.surface": "#FAFAFA",
        "bg.card": "#FFFFFF",
        "fg.default": "#1A1A1A",
        "fg.muted": "#6B7280",
        "accent": "#2563EB",
        "success": "#16A34A",
        "warning": "#D97706",
        "danger": "#DC2626",
        "overtime": "#7C3AED",
        "inprogress_bg": "#FEF3C7",
    },
    ThemeMode.DARK: {
        "bg.surface": "#1E1E1E",
        "bg.card": "#2D2D2D",
        "fg.default": "#E0E0E0",
        "fg.muted": "#9CA3AF",
        "accent": "#3B82F6",
        "success": "#22C55E",
        "warning": "#F59E0B",
        "danger": "#EF4444",
        "overtime": "#A78BFA",
        "inprogress_bg": "#422006",
    },
}


def resolve_theme_mode(mode: str | ThemeMode | None) -> ThemeMode:
    """Resolves a stored theme setting (e.g. from SettingsManager) to a
    concrete ``COLORS`` key. ``ThemeMode.SYSTEM`` (no OS dark-mode detection
    yet), ``None``, and any other unrecognized value fall back to
    ``ThemeMode.LIGHT``.

    Views that build their own tag/foreground colors (treeviews, labels)
    should use this instead of hardcoding ``COLORS[ThemeMode.LIGHT]`` so they
    honor the active theme mode the same way ``apply_theme`` does.
    """
    if mode is None:
        return ThemeMode.LIGHT
    try:
        candidate = ThemeMode(mode)
    except ValueError:
        return ThemeMode.LIGHT
    return candidate if candidate in COLORS else ThemeMode.LIGHT


def apply_theme(mode: ThemeMode = ThemeMode.LIGHT) -> ThemeMode:
    """Applies theme to the default root window. Returns the effective mode."""
    if mode == ThemeMode.SYSTEM:
        mode = ThemeMode.LIGHT

    sv_ttk.set_theme(mode)

    _configure_named_styles(mode)
    return mode


def _configure_named_styles(mode: ThemeMode) -> None:
    """Registers custom ttk styles using semantic color tokens."""
    c = COLORS.get(mode, COLORS[ThemeMode.LIGHT])
    style = ttk.Style()

    style.configure(
        "Accent.TButton", foreground=c["fg.default"], background=c["accent"]
    )
    style.configure(
        "Danger.TButton", foreground=c["fg.default"], background=c["danger"]
    )
    style.configure(
        "Success.TButton", foreground=c["fg.default"], background=c["success"]
    )
    style.configure("Card.TFrame", background=c["bg.card"])
    style.configure(
        "DayHeader.TLabel", foreground=c["fg.muted"], font=("Helvetica", 10, "bold")
    )
    style.configure(
        "Total.TLabel", foreground=c["fg.default"], font=("Helvetica", 11, "bold")
    )
    style.configure("StatusBar.TLabel", foreground=c["fg.muted"], font=("Helvetica", 9))
    style.configure("OpenRecord.TFrame", background=c["inprogress_bg"])
    style.map(
        "Treeview",
        background=[("selected", c["accent"])],
        foreground=[("selected", "#FFFFFF")],
    )
