# Visual Design System

> Detail doc for [DESIGN.md](../DESIGN.md) §16 (Visual Design System).

Goal: kill the "stock Tk" look. One `theme/style.py` owns all appearance; no view hard-codes colors or fonts.

## 16.1 Theme loading

`sv_ttk` is a required dependency (listed in `requirements.txt`, imported
unconditionally at the top of `theme/style.py`) — there is no
`try/except ImportError` fallback to a stock ttk theme.

```python
# theme/style.py
class ThemeMode(StrEnum):
    """Selectable ttk theme mode: light, dark, or system-following."""
    LIGHT = "light"
    DARK = "dark"
    SYSTEM = "system"


def resolve_theme_mode(mode: str | ThemeMode | None) -> ThemeMode:
    """Resolves a stored theme setting (e.g. from SettingsManager) to a
    concrete COLORS key. ThemeMode.SYSTEM (no OS dark-mode detection yet),
    None, and any unrecognized value fall back to ThemeMode.LIGHT."""
    ...


def apply_theme(mode: ThemeMode = ThemeMode.LIGHT) -> ThemeMode:
    """Applies theme to the default root window. Returns the effective mode."""
    if mode == ThemeMode.SYSTEM:
        mode = ThemeMode.LIGHT
    sv_ttk.set_theme(mode)
    _configure_named_styles(mode)   # custom ttk styles below
    return mode
```

`apply_theme` takes no `root` parameter — `sv_ttk.set_theme()` operates on
the default root window implicitly. It returns the effective `ThemeMode`
(useful when `ThemeMode.SYSTEM` resolves to `LIGHT`). Views that build
their own tag/foreground colors (treeviews, labels) should call
`resolve_theme_mode()` rather than hardcoding `COLORS[ThemeMode.LIGHT]`, so
they honor the active theme mode the same way `apply_theme` does.

## 16.2 Semantic color tokens

Defined once, referenced by name. Light values shown; dark variants in the same dict.

| Token | Light | Use |
|---|---|---|
| `bg.surface` | `#FAFAFA` | Window / tab background |
| `bg.card` | `#FFFFFF` | Grouped list, cards |
| `fg.default` | `#1A1A1A` | Primary text |
| `fg.muted` | `#6B7280` | Day headers, hints, secondary |
| `accent` | `#2563EB` | Buttons, selection, focus ring |
| `success` | `#16A34A` | "✓ Done", clock-in green |
| `warning` | `#D97706` | "X.Xh left", over-balance |
| `danger` | `#DC2626` | Clock-out, delete, validation errors |
| `overtime` | `#7C3AED` | "−2.0h overtime" |
| `inprogress` | `#FEF3C7` | Open-record row background + "in progress" text label |

> **All status indicators must include a text label or icon — never color alone** (accessibility, color-blind safe). Paired presentation: "✓ Done", "⚠ 3.5h left", "⏎ −2.0h overtime", "[in progress]".

## 16.3 Typography & spacing

- Fonts: UI `Segoe UI`/`Helvetica` 10pt; numeric totals tabular 11pt **bold**; monospace (`Consolas`) for time columns so `09:00–17:00` aligns.
- Spacing scale (px): `4, 8, 12, 16, 24`. All `padding`/`pady`/`padx` pick from this scale — no arbitrary values.
- Named ttk styles: `Accent.TButton` (primary), `Danger.TButton` (clock-out/delete), `Card.TFrame`, `DayHeader.TLabel`, `Total.TLabel`.

## 16.4 Custom-drawn elements

- Clock In/Out are large `Accent.TButton`/`Danger.TButton` with leading glyphs (▶ / ■).
- Grouped record list uses a `ttk.Treeview` with `tag_configure` per state (`open`, `selected`, `overtime`) rather than ad-hoc frames — gives native selection, keyboard nav, and column sorting for free.
- Optional toolbar icons from `resources/icons/` (16px PNG); absent icons degrade to text labels.

## 16.5 Dark mode

- Toggle in Settings + respect OS preference where detectable. Persisted in database via the `app_config` table (`"theme": "light"|"dark"|"system"`).
- All views read tokens, so dark mode is a single `apply_theme(ThemeMode.DARK)` re-style + Treeview tag refresh.
