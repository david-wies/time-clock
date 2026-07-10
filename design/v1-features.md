# Additional v1 Features

> Detail doc for [DESIGN.md](../DESIGN.md) §21 (Additional v1 Features). These were originally deferred but are now in scope for v1.

## 21.1 Public Holidays Auto-Import

- Settings → Time Clock gains a **Country/Region** selector (default: none) and an **"Import holidays for year"** button.
- Uses the `holidays` library — a required dependency, listed in `requirements.txt` and imported unconditionally at the top of `views/settings_dialog.py` (no `try/except ImportError` guard; see CLAUDE.md's import conventions) — to enumerate public holidays for the chosen region + year.
- Each holiday becomes a `work_day_exception` row with `hours = 0` and `label = <holiday name>` — reusing the existing exception mechanism (see [data-model.md](data-model.md) §3, DESIGN.md §5.4). No new table.
- Conflict handling: respects `UNIQUE(date)` — existing exception on a date is **kept**, import skips it and reports "N added, M skipped (already set)".
- Holidays therefore flow automatically into the daily-target logic (0h target ⇒ "Day off").
- **Jewish/Israeli holidays**: when country is set to `IL` (Israel) or `JewishHolidays` locale is selected, the `holidays` library's Israel support is used. This includes Rosh Hashana, Yom Kippur, Sukkot, Passover, Shavuot, Independence Day, etc. These are imported as `work_day_exception` rows exactly like any other country's holidays.
- Country/Region is **optional** — app functions fully without it. Selector defaults to blank ("None"); no import is attempted until a region is chosen.

## 21.2 Reports (PDF summary)

- New **`File → Reports`** menu (distinct from raw Export, DESIGN.md §14): generates a formatted summary PDF, not a data dump.
- Period selector: **Month / Quarter / Year** + year picker.
- Content: worked vs target totals, running overtime balance (see [time-and-balance.md](time-and-balance.md) §18.3), vacation used/remaining + carry-over, sickness used/remaining, per-month breakdown table.
- Engine: `reportlab` — a required dependency (listed in `requirements.txt`, imported unconditionally in `views/report_dialog.py` and `views/export_dialog.py`, same as PDF export §14); shares table-styling helpers with §14. No fallback if the package is somehow missing — it is a hard runtime dependency, not an optional feature.
- Implemented in `views/report_dialog.py` + `core/report.py` (pure data assembly → testable without PDF rendering).

## 21.3 Overtime Tracking (configurable rate)

- Builds directly on the running balance ([time-and-balance.md](time-and-balance.md) §18.3).
- Settings → Time Clock: **overtime rate** (multiplier, default `1.0`) and **balance period** (week/month/year, default month).
- `core/balance.py` exposes `overtime(period) → (raw_hours, weighted_hours)` where `weighted = raw × rate` for positive balance.
- Header + Reports show both: `Overtime: +5.0h (×1.5 = 7.5h)`. Rate only applies to surplus; deficit shown raw.
- Pure function, covered by [testing.md](testing.md) §20.2 tests (add rate cases).

## 21.4 Tray Icon + Quick Clock-In/Out

- `pystray` (+ `Pillow`) — required dependencies, listed in `requirements.txt` and imported unconditionally in `views/tray.py` (no `try/except ImportError` guard). Per CLAUDE.md's "Key Gotchas", the graceful-fallback pattern described elsewhere in this doc set is for distribution packaging only, not the source tree — the tray module always assumes the deps are present.
- Tray icon reflects clock state via color (uses `success`/`fg.muted` tokens, [visual-design.md](visual-design.md) §16.2): active = green, idle = grey.
- Right-click menu: **Clock In**, **Clock Out**, **Open**, **Quit**. Menu items call the same `TimeClockController.clock_in/clock_out` (DESIGN.md §19) — no logic duplication.
- Tray actions publish `CLOCK_STATE_CHANGED` (DESIGN.md §17) so the main window stays in sync if open.
- Setting: **"Minimize to tray"** (default off) — window close → hide to tray instead of exit when enabled.
- Lives in `views/tray.py`, started from `main.py` guarded only by the "Minimize to tray" setting (the deps are always present, not conditionally checked).
- **Thread Safety & DB Concurrency**: Because the system tray run-loop executes on a separate thread, all actions that invoke controller methods or touch the database must be marshalled back to the main tkinter thread (e.g., using `root.after()` or `root.event_generate()`) to avoid SQLite concurrency violations. Database connections should utilize WAL mode.

## 21.5 Break Presets

- Add/Edit Time Record dialog (DESIGN.md §5.5) gains quick-set buttons next to the Break field: **`[15m] [30m] [45m] [1h]`** plus the existing manual `HH:MM` entry.
- Clicking a preset sets the field and re-runs the live net-duration calc. Purely a view-layer convenience; no model/schema change.
- Preset list configurable in Settings (defaults above), stored in the `app_config` table (see [data-model.md](data-model.md) §3).

## 21.6 Week / Month View Toggle

- Time Clock tab header gains a segmented control: **`[ Week | Month ]`** (default Month, persisted in the `app_config` table).
- **Month view**: existing grouped-by-day display (DESIGN.md §5.3).
- **Week view**: 7-day strip (Mon–Sun) for the selected week with prev/next-week nav; each day shows its records + daily subtotal and target delta; week footer shows the running weekly balance ([time-and-balance.md](time-and-balance.md) §18.3).
- Both views share the same `ttk.Treeview` and tag styling ([visual-design.md](visual-design.md) §16.4); the toggle swaps the grouping/query, not the widget.
- Week navigation reuses Year/Month filter state; selecting a day in week view scrolls month view to it and vice-versa.

## 21.7 Hebrew Calendar Date Display

Always shown — `hdate` is a required dependency.

- **Dependency**: `hdate` (PyPI: `hdate`). Listed in `requirements.txt`; imported unconditionally.
- **Conversion utility**: `core/hebrew_date.py` — single function `to_hebrew_label(d: date) -> str` that always returns a formatted Hebrew date string (e.g., `"י"ז סיוון תשפ"ו"`).
- **Display locations**:
  - Time Clock grouped list day headers: `── Monday, June 1 / י"ז סיוון תשפ"ו (7.5h) ──`
  - Vacation list: "Hebrew Date" column next to "Date" column (always visible)
  - Sickness list: "Hebrew Date" column next to "Date" column (always visible)
  - Export: "Hebrew Date" column always included in CSV/Excel/PDF
- **Column width**: fixed monospace-aligned column; uses the same `Consolas` font as time columns ([visual-design.md](visual-design.md) §16.3).
- **No settings toggle**: Hebrew dates are always shown; no `show_hebrew_dates` setting.
- **No schema change**: Hebrew dates are always computed on the fly from the stored Gregorian ISO date. Never persisted.

```python
# core/hebrew_date.py
def to_hebrew_label(d: date) -> str:
    return str(HebrewDate.from_gdate(d))[::-1]
```
