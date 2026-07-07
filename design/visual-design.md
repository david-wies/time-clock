# Visual Design System

> Detail doc for [DESIGN.md](../DESIGN.md) §16 (Visual Design System).

Goal: kill the "stock Tk" look. One `theme/style.py` owns all appearance; no view hard-codes colors or fonts.

## 16.1 Theme loading (graceful)

```python
# theme/style.py
def apply_theme(root, mode="light"):
    try:
        import sv_ttk            # modern flat theme
        sv_ttk.set_theme(mode)
    except ImportError:
        from tkinter import ttk
        ttk.Style().theme_use("clam")   # best stock fallback
    _configure_named_styles(root)        # custom ttk styles below
```

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
- All views read tokens, so dark mode is a single `apply_theme(root, "dark")` re-style + Treeview tag refresh.
