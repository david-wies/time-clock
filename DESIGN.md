# Time Clock Application — Design Document

## Document Map

This is the main design document — architecture, UI layout, and contracts between layers. The more involved subsystems have their own detail doc; each linked section below gives a condensed summary here and the full spec there.

| Detail doc | Covers |
|---|---|
| [design/data-model.md](design/data-model.md) | Full SQLite schema (§3), domain dataclasses & enums (§15) |
| [design/data-flow.md](design/data-flow.md) | Step-by-step mutation sequences (§10) |
| [design/visual-design.md](design/visual-design.md) | Theme system, color tokens, typography (§16) |
| [design/time-and-balance.md](design/time-and-balance.md) | Wall-clock/DST semantics, running overtime balance (§18) |
| [design/testing.md](design/testing.md) | Test strategy, fixtures, coverage targets (§20) |
| [design/v1-features.md](design/v1-features.md) | Holidays import, reports, tray icon, etc. (§21) |

## 1. Technology Stack

| Layer | Choice | Rationale |
|---|---|---|
| Language | Python 3.14+ | User requirement |
| GUI Framework | tkinter + ttk (stdlib) + tkcalendar | Stdlib, no deps for core UI; tkcalendar for date picker |
| Theme | `sv-ttk` (required) | Modern flat light/dark ttk theme (see [visual-design.md](design/visual-design.md)) |
| Data Persistence | SQLite via sqlite3 (stdlib) | Local, single-file, no setup |
| Domain Layer | `@dataclass` + `enum.Enum` (stdlib) | Typed records, no ORM; one source of truth for fields (see [data-model.md](design/data-model.md)) |
| UI Pattern | MVC + Observer event bus | View ↔ Controller ↔ Model; Model change broadcasts via event bus (§17) since tkinter has no native signals |
| Type Checking | `mypy --strict` (dev only) | Catch field/enum mistakes before runtime |
| Packaging | PyInstaller (optional) | Single executable if needed |

## 2. Application Architecture

```
                        ┌─ Layer stack ────────────────────┐
                        │  Views       (tkinter widgets)    │
                        │     ↓ user actions                │
                        │  Controllers (validation, orchest.)│
                        │     ↓ mutations                   │
                        │  Models      (CRUD, queries)      │
                        │     ↓ SQL                        │
                        │  Database    (SQLite)             │
                        └──────────────────────────────────┘
                        Domain / Core / Events shared across all layers
```

```
┌───────────────────────────────────────────────────────────────┐
│                    MainWindow (ttk.Notebook)                    │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────┐  │
│  │   TimeClockTab    │  │   VacationTab    │  │  SicknessTab │  │
│  │  (ttk.Frame)      │  │  (ttk.Frame)     │  │ (ttk.Frame)  │  │
│  └────────┬─────────┘  └────────┬─────────┘  └──────┬───────┘  │
│           │                      │                    │         │
│           ▼                      ▼                    ▼         │
│  ┌────────────────┐  ┌──────────────────┐  ┌────────────────┐  │
│  │TimeClockControl │  │ VacationControl  │  │SicknessControl │  │
│  └──────┬─────────┘  └───────┬──────────┘  └───────┬────────┘  │
│         │                    │                      │           │
│         ▼                    ▼                      ▼           │
│  ┌──────────────┐  ┌──────────────────┐  ┌────────────────┐    │
│  │TimeClockModel│  │  VacationModel    │  │ SicknessModel  │    │
│  └──────┬───────┘  └───────┬──────────┘  └───────┬────────┘    │
│         │                  │                      │             │
│         └──────────────────┼──────────────────────┘             │
│                            ▼                                    │
│                 ┌──────────────────────┐                        │
│                 │   Database (SQLite)   │                        │
│                 └──────────────────────┘                        │
│  ┌──────────────────────────────────────────────────────┐       │
│  │  SettingsManager (SQLite)     │  Core utilities       │       │
│  │  Domain types (@dataclass)    │  EventBus (pub/sub)   │       │
│  └──────────────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────────────┘
```

### 2.1 Modules

| Module | File | Responsibility |
|---|---|---|
| Entry point | `main.py` | App init, dependency wiring, MainWindow creation, show |
| Domain types | `domain/` | Typed `@dataclass` records + enums — shared by all layers (§15) |
| Event bus | `core/events.py` | Publish/subscribe so Models notify Views of changes (§17) |
| Controllers | `controllers/` | Mediate View ↔ Model: validation, business rules, mutations (§19) |
| Theme | `theme/style.py` | ttk styling, palette, fonts, light/dark (§16) |
| Main window | `views/main_window.py` | ttk.Notebook tab container, menu bar |
| Time Clock tab | `views/time_clock_tab.py` | UI layout (ttk.Frame), user interactions |
| Vacation tab | `views/vacation_tab.py` | UI layout (ttk.Frame), user interactions |
| Sickness tab | `views/sickness_tab.py` | UI layout (ttk.Frame), user interactions |
| Settings dialog | `views/settings_dialog.py` | Shared & per-tab settings (tk.Toplevel) |
| Date picker | `views/date_picker.py` | tkcalendar.DateEntry wrapper or custom popup |
| Export dialog | `views/export_dialog.py` | Export UI: format selection, date range, generation |
| Help viewer | `help/` | Static HTML with searchbox + TOC, opened in default browser |
| Models | `models/` | Data access, business logic |
| Database | `db/database.py` | Schema, CRUD, migrations |
| Settings | `settings.py` | Read/write config persistence (via SQLite app_config) |

## 3. Data Model (SQLite Schema)

| Table | Purpose |
|---|---|
| `work_day_target` | Default daily-hours target per day-of-week |
| `work_day_exception` | Date-specific target override (holidays, half-days) — takes priority over `work_day_target` |
| `time_record` | Clock-in/out records: date, start/end `HH:MM`, break minutes, work_type, office, note |
| `vacation_settings` | Yearly vacation allowance + max carry-over, keyed by year |
| `vacation_record` | Vacation/holiday/unpaid/carry-over entries |
| `sickness_settings` | Yearly sick-day allowance, keyed by year |
| `sickness_record` | Sick-hour entries |
| `carry_over_log` | Audit trail of vacation-hour transfers between years |
| `app_config` | All settings/preferences (JSON value per key) — replaces settings files |

### 3.1 Duration Calculation

```text
net_duration = (end_time - start_time) - break_minutes
```

Computed on read, never persisted — DB stores raw start/end/break.

> **Time semantics (important).** `start_time`/`end_time` are **wall-clock local** `HH:MM`. The schema default `datetime('now')` returns **UTC**, so it is used **only** for the audit columns `created_at`/`updated_at`, never for `start_time`/`end_time`. See [time-and-balance.md](design/time-and-balance.md) (§18) for DST and overnight handling.

Full `CREATE TABLE` SQL, `CHECK` constraints, and indexes: [design/data-model.md](design/data-model.md) §3.

## 4. MainWindow Layout

```
┌──────────────────────────────────────────────────────────┐
│ File  Settings  Help                                     │
├──────────────────────────────────────────────────────────┤
│ [Time Clock]  [Vacation]  [Sickness]                      │
│                                                          │
│   Content depends on active tab (see below)              │
│                                                          │
├──────────────────────────────────────────────────────────┤
│ Ready — Double-click record to edit    |  42 records     │
└──────────────────────────────────────────────────────────┘
```

- `Settings` menu → opens `SettingsDialog` (tab-specific sections)
- `File → Export` → submenu with per-tab export options (see §14)
- `Help → About / Usage Guide` → opens `help/index.html` in default browser via `webbrowser.open()`. Single-page HTML with built-in searchbox + table of contents sidebar. Content sections:

  | Section | Content |
  |---|---|
  | Getting Started | First launch, setting daily targets, clock-in/out basics |
  | Time Clock | Record list, clock in/out, add/edit/delete, daily target, overtime |
  | Vacation | Adding records, carry-over, balance display |
  | Sickness | Adding records, hours-to-days conversion, balance rules |
  | Settings | Daily targets, date exceptions, offices, vacation/sickness allowances |
  | Export | CSV/Excel/PDF per tab, date range filtering |
  | Keyboard Shortcuts | Full shortcut table (§4.2) |
  | FAQ | "What happens if I close the app while clocked in?", overnight shifts, DST

- Status bar at bottom: contextual hints, record count for current filter, clock-in status, active-tab indicator

### 4.1 Minimum Dimensions

| Window | Min Size | Rationale |
|---|---|---|
| MainWindow | 800×600 | Comfortable for grouped table + summary |
| TimeRecordDialog | 420×380 | Fits all fields without scroll |
| VacationRecordDialog | 400×320 | Fewer fields |
| SickRecordDialog | 400×300 | Fewer fields |
| CarryOverDialog | 360×200 | Simple form |
| SettingsDialog | 600×560 | Grid of checkboxes + inputs, 4 sections |
| DatePickerPopup | 320×340 | Fallback date picker (only when tkcalendar unavailable) |

### 4.2 Keyboard Shortcuts

| Shortcut | Action | Scope |
|---|---|---|
| Ctrl+N | New time record | Time Clock tab |
| Ctrl+Shift+N | New vacation record | Vacation tab |
| Ctrl+Shift+S | New sick record | Sickness tab |
| Ctrl+E | Edit selected record | All tabs |
| Delete | Remove selected record | All tabs |
| Ctrl+D | Clock out (close active record) | Time Clock tab |
| Ctrl+S | Open settings | Global |
| F5 | Refresh data | All tabs |
| F1 | Open help / about | Global |
| Ctrl+F | Focus search (future) | All tabs |

## 5. Time Clock Tab

### 5.1 Layout

```
┌──────────────────────────────────────────────────────────┐
│ Today: 26/06/2026  |  Target: 8.0h  |  Remaining: 3.5h  │
├──────────────────────────────────────────────────────────┤
│ ┌─ Year: [2026 ▼]  Month: [June ▼] ──────────────────┐  │
│ │                                                     │  │
│ │  ─── Monday, June 1 ───                             │  │
│ │  09:00-12:30  in_site (Office A)  design API  ...   │  │
│ │  13:30-17:00  remote               code review ...  │  │
│ │  ─── Tuesday, June 2 ───                            │  │
│ │  08:30-16:30  road                 client visit ...  │  │
│ │  ─── June 2026 Totals ───                            │  │
│ │  22 days, 168.0h worked                             │  │
│ │                                                     │  │
│ └─────────────────────────────────────────────────────┘  │
│                                                          │
│ [▶ Clock In] [■ Clock Out]  |  [+ Add Record] [✏ Edit] [🗑 Delete] │
└──────────────────────────────────────────────────────────┘
```

### 5.2 Quick Clock-In / Clock-Out

Two prominent one-click buttons above the record list:

| Button | Action | Color |
|---|---|---|
| **▶ Clock In** | Creates new `time_record` with `date=today, start_time=now, end_time=NULL, work_type=last-used` | Green |
| **■ Clock Out** | Finds today's record where `end_time IS NULL`, sets `end_time=now`. If multiple open records exist, prompt which to close | Red |

- If user is already clocked in (open record exists), **Clock In** shows warning: "Open record exists. Clock out first, or start new record anyway?" — user can proceed for parallel records (e.g., work type change mid-day)
- First clock-in of the day may prompt for work_type (stored as preference for subsequent same-day clock-ins)
- Open records appear in the grouped view with yellow background + "in progress" badge
- During an active clock-in, the "remaining today" counter auto-refreshes every 60s via `root.after()` to show running duration
- Work_type defaults to last used value (stored in settings)

### 5.3 Grouped Display

- Primary sort: `date DESC`
- Within each day, sort by `start_time ASC`
- Grouped by month with collapsible headers
- Within each month, grouped by day with day header showing daily subtotal and Hebrew date: `── Monday, June 1 / י"ז סיוון תשפ"ו (7.5h) ──`
- Each row: `start-end | break | type + office | note | net_duration`
- Open records (no end_time): yellow background, "in progress" label, duration shows elapsed so far
- Month footer: total hours for that month
- Selected row highlighted
- Double-click any row → opens edit dialog for that record
- Each workday can have multiple records (contiguous blocks with breaks) — no break field within a single record needed since break is per-record
- Hebrew date always shown in day headers: `── Monday, June 1 / י"ז סיוון תשפ"ו (7.5h) ──`

### 5.4 Daily Target Calculation

1. Check `work_day_exception` for today's date — if match, use that hours value
2. If no exception, read `work_day_target` for current `day_of_week`
3. Sum `net_duration` for today's `time_record` rows:
   `SUM((julianday(date || ' ' || end_time) - julianday(date || ' ' || start_time)) * 24 - break_minutes / 60.0)`
   Open records (no end_time) compute elapsed time from start to now
4. Display: "Remaining: X.Xh" (target − sum)
5. If sum ≥ target → green text "✓ Done"
6. If sum < target → orange/red text "X.Xh left"
7. No target set → grey "No target for today"
8. If sum > target → remaining is negative (overtime). Show with "Overtime" label in purple/blue: "⏎ −2.0h overtime"
9. If an open clock-in exists, auto-refresh the remaining counter every 60s via `root.after(60000, refresh)`

### 5.5 Add/Edit Record Dialog

```
┌─ Time Record ───────────────────────────────────────────┐
│ Date:  [26/06/2026 [📅▼]]    ← DateEntry with dropdown  │
│ Start: [09:00]   End: [17:00]                           │
│ Break: [00:30] (HH:MM, unpaid) → Net duration: 7.5h    │
│ Type:  ○ In Site  ○ Road  ○ Remote                      │
│ Office: [Office A ______▼] (only enabled for in_site)   │
│ Note:  [__________________________________]              │
│                                                         │
│              [Cancel]    [Save]                          │
└─────────────────────────────────────────────────────────┘
```

- Date field uses `tkcalendar.DateEntry` — inline dropdown, no separate popup
- Net duration auto-calculates as start/end/break change
- Office combo populated from settings (configurable list)

### 5.6 Input Validation

| Field | Rule | Error Message |
|---|---|---|
| date | Required, valid ISO date | "Please enter a valid date." |
| start_time | Required, format HH:MM | "Start time must be in HH:MM format." |
| end_time | Optional, format HH:MM. NULL = clocked in | "End time must be in HH:MM format." |
| end_time > start_time | Checked only when end_time present AND end_time > start_time | "End time must be after start time." |
| overnight (end_time < start_time) | Allowed with warning (see §5.7) | "End time is before start — treating as overnight shift." |
| break | Optional, format HH:MM, ≤ shift_duration | "Break cannot exceed shift length." |
| work_type | Required, one of enum | "Please select a work type." |
| office | Required if work_type = in_site | "Please select or enter an office." |
| note | Optional, max 500 chars | "Note is too long (max 500 characters)." |
| overlapping | No overlap with existing records on same date | "Record overlaps with an existing time record." |

### 5.7 Overnight Shift Handling

If `end_time < start_time` (e.g., 22:00 → 06:00):

- Assume shift crosses midnight into next day
- Show warning: "End time is before start time — treating as overnight shift."
- Store as-is in DB. Duration computed as `(24:00 - start) + (end - 00:00) - break`.
- Display tooltip on row: "Overnight shift → next day"

## 6. Vacation Tab

### 6.1 Vacation Pool Rules

- **Vacation Types**: The application supports multiple informative vacation types:
  - `annual_leave`: Standard paid vacation days. Draws from the annual pool (**debit**).
  - `public_holiday`: Paid statutory public holidays. Draws from the annual pool (**debit**).
  - `special_leave`: Paid special leave (e.g., bereavement, wedding, jury duty). Draws from the annual pool (**debit**).
  - `unpaid_leave`: Unpaid time off. Does **not** draw from the annual pool (informational, **no pool impact**).
  - `carry_over`: Hours transferred from the previous year. Adds to the annual pool (**credit**).
- **Balance Calculation**:
  - `Total Pool = (hours_per_year for year) + SUM(hours of carry_over records for year)`
  - `Used Pool = SUM(hours of annual_leave, public_holiday, special_leave records for year)`
  - `Remaining Balance = Total Pool - Used Pool`
- Sickness is tracked in a completely separate pool (§7).

### 6.2 Layout

```
┌──────────────────────────────────────────────────────────────────────┐
│ Year: [2026 ▼]  Month: [All ▼]                                      │
│ Vacation: 120.0h / 170.0h available  |  Remaining: 50.0h            │
│ (annual: 104.0h, holiday: 16.0h, carry_over: +10.0h)                │
├──────────────────────────────────────────────────────────────────────┤
│ ┌──────────────────────────────────────────────────────────────────┐ │
│ │  Date        Hebrew Date      Type          Hours  Note          │ │
│ │  01/01/2026  א׳ טבת תשפ"ו   carry_over    10.0h  Carry-over 25 │ │
│ │  05/01/2026  ה׳ טבת תשפ"ו   annual_leave   8.0h  Ski trip      │ │
│ │  10/04/2026  י"ב ניסן תשפ"ו public_holiday 8.0h  Easter        │ │
│ │  12/05/2026  י"ד אייר תשפ"ו unpaid_leave   8.0h  Personal      │ │
│ │  15/07/2026  כ"א תמוז תשפ"ו annual_leave   8.0h  Summer vac.  │ │
│ │  ──────────────────────────────────────────────────────────────  │ │
│ │  Total debits: 24.0h (14% of available pool)                    │ │
│ └──────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│ [+ Add Record]  [✏ Edit Record]  [🗑 Remove Record]                 │
│ [+ Add Carry-Over Hours]                                             │
└──────────────────────────────────────────────────────────────────────┘
```

- Hebrew Date column always shown, populated by `core/hebrew_date.py`.

### 6.3 Add/Edit Vacation Record Dialog

```
┌─ Vacation Record ───────────────────────────────────────────────────────────┐
│ Date:  [15/07/2026 [📅▼]]  ← DateEntry with dropdown                        │
│ Hours: [8.0]                                                                │
│ Type:  ○ Annual Leave  ○ Public Holiday  ○ Special Leave                     │
│        ○ Unpaid Leave  ○ Carry-over                                         │
│ Note:  [Summer vacation __________________________________________________] │
│                                                                             │
│                            [Cancel]    [Save]                               │
└────────────────────────────────────────────────-----------------------------┘
```

### 6.4 Carry-Over Dialog

```
┌─ Add Carry-Over Hours ──────────────────────────────┐
│ Previous year (2025): unused 24.0h                   │
│ Max transferable:              12.0h                 │
│ Already transferred to 2026:    0.0h                 │
│ Add to this year:    [12.0]   (max 12.0)             │
│                                                      │
│              [Cancel]    [Add]                       │
└──────────────────────────────────────────────────────┘
```

- Year and Month filters at top control which records are displayed (default: current year, all months)
- `carry_over_log` table tracks each transfer: from_year, to_year, hours
- Prevent double-counting: check `SUM(hours) FROM carry_over_log WHERE from_year = Y-1 AND to_year = Y`
- Available carry-over = `MIN(max_carry_over, prev_year_surplus - already_transferred)`
- Each carry-over creates a **separate `vacation_record`** with `vtype = 'carry_over'` and note "Carry-over from YYYY" so it appears in the main list
- Settings define `max_carry_over` — enforced in dialog

### 6.5 Input Validation

| Field | Rule | Error Message |
|---|---|---|
| date | Required, valid ISO date | "Please enter a valid date." |
| hours | Required, ≥ 0.5, ≤ 24 | "Hours must be between 0.5 and 24." |
| hours | Must not exceed remaining yearly balance + warning | "This exceeds your remaining vacation balance. Save anyway?" |
| vtype | Required, one of: annual_leave, public_holiday, special_leave, unpaid_leave, carry_over | "Please select a vacation type." |
| note | Optional, max 500 chars | "Note is too long (max 500 characters)." |

## 7. Sickness Tab

### 7.1 Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│ Year: [2026 ▼]  Month: [June ▼]                                    │
│ Sick days: 2.5 / 10.0 used  |  Remaining: 7.5 days                │
├─────────────────────────────────────────────────────────────────────┤
│ ┌───────────────────────────────────────────────────────────────┐  │
│ │  Date        Hebrew Date       Hours  Note                    │  │
│ │  15/02/2026  כ"ז שבט תשפ"ו   8.0h   Flu                    │  │
│ │  10/03/2026  י' אדר תשפ"ו    4.0h   Dentist appointment     │  │
│ │  22/05/2026  כ"ד אייר תשפ"ו  8.0h   Stomach bug             │  │
│ │  ───────────────────────────────────────────────────────────  │  │
│ │  Total: 20.0h (2.5 days)                                     │  │
│ └───────────────────────────────────────────────────────────────┘  │
│                                                                     │
│ [+ Add Record]  [✏ Edit Record]  [🗑 Remove Record]                │
└─────────────────────────────────────────────────────────────────────┘
```

- Hebrew Date column always shown, populated by `core/hebrew_date.py`.

- Hours-to-days conversion: `days = hours / daily_target` (average), or display both
- Grouped by month with collapsible headers, same pattern as Time Clock

### 7.2 Add/Edit Sick Record Dialog

```
┌─ Sick Record ───────────────────────────────────────┐
│ Date:  [15/02/2026 [📅▼]]                            │
│ Hours: [8.0]                                         │
│ Note:  [Flu ___________________________________]    │
│                                                      │
│              [Cancel]    [Save]                      │
└──────────────────────────────────────────────────────┘
```

### 7.3 Input Validation

| Field | Rule | Error Message |
|---|---|---|
| date | Required, valid ISO date | "Please enter a valid date." |
| hours | Required, ≥ 0.5, ≤ 24 | "Hours must be between 0.5 and 24." |
| hours | Must not exceed remaining yearly sick days | "This exceeds your remaining sick day balance. Save anyway?" |
| note | Optional, max 500 chars | "Note is too long (max 500 characters)." |

### 7.4 Sick Day Balance Rules

- Sick days reset each year (no carry-over — distinct from vacation)
- Balance is purely hours-based: `used_hours = SUM(hours)` for the year, `remaining_hours = allowance_hours - used_hours` — no day-equivalent conversion (see [data-flow.md §10.6](design/data-flow.md))
- No distinction between types — single pool for all illness

## 8. Settings Dialog

```
┌─ Settings ───────────────────────────────────────────┐
│                                                      │
│ ┌─ Time Clock ────────────────────────────────────┐  │
│ │  Daily work hours:                              │  │
│ │  ☑ Mon [8.0]  ☑ Tue [8.0]  ☑ Wed [8.0]        │  │
│ │  ☑ Thu [8.0]  ☑ Fri [8.0]  ☐ Sat [0.0]        │  │
│ │  ☐ Sun [0.0]                                    │  │
│ │                                                  │  │
│ │  Offices:                                         │  │
│ │  ┌────────────────────┐  [+ Add]                  │  │
│ │  │ Office A           │  [× Remove]               │  │
│ │  │ Office B           │  [✏ Edit]                 │  │
│ │  │ Office C           │                            │  │
│ │  └────────────────────┘                            │  │
│ └──────────────────────────────────────────────────┘  │
│ ┌─ Date Exceptions ────────────────────────────────┐  │
│ │  Override target for specific dates:              │  │
│ │  ┌──────────────────────┐                         │  │
│ │  │ 24/12/2025  4.0h  Christmas Eve  │  [+ Add]   │  │
│ │  │ 25/12/2025  0.0h  Christmas Day  │  [× Remove] │  │
│ │  │ 01/01/2026  0.0h  New Year       │  [✏ Edit]   │  │
│ │  └──────────────────────┘                         │  │
│ └──────────────────────────────────────────────────┘  │
│ ┌─ Vacation ──────────────────────────────────────┐  │
│ │  Hours per year:    [160.0]                      │  │
│ │  Max carry-over:    [40.0]                       │  │
│ └──────────────────────────────────────────────────┘  │
│ ┌─ Sickness ──────────────────────────────────────┐  │
│ │  Days per year:    [10.0]                        │  │
│ └──────────────────────────────────────────────────┘  │
│                                                      │
│              [Cancel]    [Save]                       │
└──────────────────────────────────────────────────────┘
```

- Checkbox enables/disables hour input per day-of-week
- Date exceptions take priority over day-of-week targets. Add dialog: date picker + hours + optional label
- Office list stored as JSON array in settings (stored in `app_config` table)
- Settings stored inside the database via the `app_config` table (fully backed up with DB)

## 9. Date Picker

### 9.1 Primary: tkcalendar.DateEntry (inline)

```
┌──────────────────┐
│ 26/06/2026 [📅▼] │  ← DateEntry with dropdown calendar
└──────────────────┘
```

- Embedded directly in record dialogs — no popup needed
- Dropdown shows month grid when user clicks arrow

### 9.2 Fallback: Custom Popup (no tkcalendar)

```
┌─ Select Date ──────┐
│   < June 2026 >    │
│ Mo Tu We Th Fr Sa Su│
│  1  2  3  4  5  6  7│
│  8  9 10 11 12 13 14│
│ 15 16 17 18 19 20 21│
│ 22 23 24 25 26 27 28│
│ 29 30               │
│                     │
│  [Cancel]  [Select] │
└─────────────────────┘
```

- `tk.Toplevel` with grid of `ttk.Button` widgets
- Returns `datetime.date` → ISO string

## 10. Data Flow

High-level mutation flow: View → Controller (validation, orchestration) → Model (business rules, CRUD) → DB → `EventBus.publish` → subscribed tabs refresh. Full step-by-step sequences for each flow below are in [design/data-flow.md](design/data-flow.md).

- **§10.1 Time Clock — Add Record**: dialog validates, controller saves, model checks overlap, event triggers table + remaining-today refresh.
- **§10.2 Vacation Usage Calculation**: sums debits/credits for the year, folds in carry-over from the prior year, computes remaining balance.
- **§10.3 Vacation — Add Carry-Over**: dialog computes available transfer, writes both a `carry_over_log` row and a `vacation_record`.
- **§10.4 Clock-In**: warns on an already-open record, inserts a new open `time_record`, starts the 60s auto-refresh.
- **§10.5 Clock-Out**: closes the open record (prompts if more than one), stops auto-refresh once none remain.
- **§10.6 Sickness Usage Calculation**: sums hours for the year against the yearly allowance (purely hours-based, no day conversion).

## 11. File Structure

```text
time-clock/
├── main.py                     # Entry point: wires Database → Models → Controllers → Views
├── DESIGN.md                   # Main design document (this file)
├── design/                     # Detail docs for the more involved subsystems
│   ├── data-model.md           # Full schema + domain types (§3, §15)
│   ├── data-flow.md            # Full mutation sequences (§10)
│   ├── visual-design.md        # Theme system, color tokens (§16)
│   ├── time-and-balance.md     # Wall-clock/DST semantics, running balance (§18)
│   ├── testing.md              # Test strategy, fixtures (§20)
│   └── v1-features.md          # Holidays import, reports, tray, etc. (§21)
├── AGENTS.md                   # Agent-facing project state & file map
├── requirements.txt            # tkcalendar, sv-ttk, holidays, reportlab, pystray, Pillow — all optional / graceful
├── tray.py                     # System-tray icon + quick clock in/out (§21.4), started from main.py
├── settings.py                 # Settings manager (reads/writes using DB app_config table)
├── domain/
│   ├── types.py                # @dataclass records: TimeRecord, VacationRecord, SicknessRecord (§15)
│   └── enums.py                # WorkType, VacationType, Weekday (§15)
├── core/
│   ├── events.py                # EventBus + Event enum — Observer mechanism (§17)
│   ├── timeutil.py             # Local-time "now", duration math, DST-safe overnight (§18)
│   ├── balance.py              # Period overtime / running-balance + rate (§18, §21.3)
│   └── report.py               # Report data assembly — period summaries (§21.2)
├── db/
│   └── database.py             # Schema, connection, migrations
├── models/
│   ├── time_clock_model.py     # TimeRecord CRUD + queries
│   ├── vacation_model.py       # VacationRecord CRUD + queries
│   └── sickness_model.py       # SicknessRecord CRUD + queries
├── controllers/
│   ├── time_clock_controller.py  # Validation orchestration, clock in/out, mutations (§19)
│   ├── vacation_controller.py    # Vacation + carry-over logic
│   └── sickness_controller.py    # Sickness logic
├── theme/
│   └── style.py                # ttk Style setup, palette, fonts, sv-ttk load/fallback (§16)
├── views/
│   ├── main_window.py          # ttk.Notebook tab container, menu bar
│   ├── time_clock_tab.py       # TimeClock tab UI
│   ├── vacation_tab.py         # Vacation tab UI
│   ├── sickness_tab.py         # Sickness tab UI
│   ├── settings_dialog.py      # Settings dialog
│   ├── date_picker.py          # tkcalendar.DateEntry wrapper / fallback popup
│   ├── time_record_dialog.py   # Add/edit time record
│   ├── vacation_record_dialog.py # Add/edit vacation record
│   ├── sick_record_dialog.py   # Add/edit sick record
│   ├── export_dialog.py        # Export format + date range selection
│   ├── report_dialog.py        # Period report → PDF (§21.2)
│   └── help_viewer.py          # Opens help/index.html in browser (F1)
├── help/
│   ├── index.html              # Single-page help: TOC sidebar + searchbox + content
│   ├── style.css               # Styling (can be inline if small)
│   └── script.js               # Search filter + TOC toggle (can be inline)
├── resources/
    └── icons/                  # Toolbar/menu icons (optional)
```

## 12. Edge Cases & Constraints

| # | Scenario | Handling |
|---|---|---|
| 1 | No target set for today | Show "No target" grey text; remaining = N/A |
| 2 | Target = 0 on weekend | Hidden or "Day off" shown |
| 3 | Overnight shift (22:00-06:00) | end_time < start_time → assume next day; warn user; compute duration as sum of two segments |
| 4 | Overlapping time records | Warn on save: "Overlaps with existing record on same date" — block save |
| 5 | Net duration negative (break > shift length) | Warn: "Break exceeds shift length." Block save unless corrected |
| 6 | Zero-length record (start = end, break = 0) | Warn: "Zero duration record. Are you sure?" Allow with confirmation |
| 7 | Vacation > yearly allowance | Show warning; allow override with confirmation |
| 8 | Carry-over exceeds max | Clamp to max_carry_over; inform user |
| 9 | Already-transferred carry-over detected | Subtract from available; display "Xh already transferred" |
| 10 | Delete last record in a day | Day header remains (empty day) or collapses (UX choice — keep header) |
| 11 | Same date used twice | Allowed (half-day annual_leave + public_holiday same day; multiple time records same day) |
| 12 | Future dates | Time records: warn but allow. Vacation: allowed by design |
| 13 | DB migration | Schema version table; `PRAGMA user_version` tracks migrations |
| 14 | Overtime displayed negative | Show "−2.0h overtime" in purple/blue, distinct from under-target orange |
| 15 | App closed while clocked in | On restart, detect record WHERE end_time IS NULL for today. Show warning: "Open record found. Clock out or delete?" Resume tracking if user continues |
| 16 | Database corruption | App ships with `time_clock.db` next to executable. Recommend user backs up periodically or enables File → Export to JSON |
| 17 | Sick day exceeds yearly allowance | Show warning; allow override with confirmation |
| 18 | Sick record on same day as time record | Allowed (worked half-day, went home sick). No automatic deduction |
| 19 | Sick record on same day as vacation record | Allowed. User manually manages overlapping absences |
| 20 | Year rollover — sick days reset | On Jan 1, sickness used counter resets to 0. Previous year records remain for history. No carry-over logic needed |
| 21 | Hours-to-days conversion when daily_target varies | Each sick record's equivalent days computed individually based on that date's `day_of_week` target. If Mon=8h target → 8h sick = 1 day. If Sat=0 target → 8h sick on Saturday capped at 1 day max |
| 22 | Date exception on sick/vacation day | Work target exception still applies for "remaining today" display. If 0h exception (holiday), remaining shows N/A |
| 23 | Multiple exceptions same date | `UNIQUE(date)` constraint prevents duplicates. Edit existing instead |

## 13. Data Backup & Portability

- SQLite DB (`time_clock.db`) lives next to the executable (or `~/.local/share/time-clock/` on Linux, `%APPDATA%` on Windows)
- All settings and preferences are stored directly inside the SQLite database in the `app_config` table (§3). No secondary settings files are required.
- **Recommendation**: user backs up the `time_clock.db` file periodically to prevent data loss.
- **Future**: `File → Import from JSON/CSV` for restoring or migrating data.

## 14. Export (v1 Feature)

### 14.1 Access

- `File → Export` menu with per-tab submenu:
  - `File → Export → Time Records`
  - `File → Export → Vacation`
  - `File → Export → Sickness`
- Each opens format selection dialog

### 14.2 Export Formats

| Format | Dependency | Notes |
|---|---|---|
| **CSV** | `csv` (stdlib) | Zero-dependency, always available. One file per tab |
| **Excel (.xlsx)** | `pandas` + `openpyxl` | Optional. Grouped sheets by month. Auto-install prompt if missing |
| **PDF** | `reportlab` | Optional. Formatted tables with month headers, totals. Auto-install prompt if missing |

### 14.3 Time Clock Export

```
┌─ Export Time Records ──────────────────────────────┐
│ Date range: [01/01/2026 [📅▼]] to [26/06/2026 [📅▼]] │
│                                                     │
│ Include: ☑ Group by month  ☑ Summary row           │
│          ☐ Only working days  ☐ Omit notes          │
│                                                     │
│ Format:  ○ CSV  ○ Excel  ○ PDF                      │
│                                                     │
│              [Cancel]    [Export]                    │
└─────────────────────────────────────────────────────┘
```

- CSV output: `date, start_time, end_time, break_minutes, work_type, office, note, net_hours`
- Monthly CSV: separate file per month or one file with month column
- PDF: same grouped layout as in-app view, with month totals

### 14.4 Vacation Export

- Columns: `date, hours, type, note`
- Summary: total used, remaining, carry-over breakdown
- Optional: separate sheet/section per year

### 14.5 Sickness Export

- Columns: `date, hours, note`
- Summary: total hours, days-equivalent, remaining balance

### 14.6 Export Flow

```
User selects File → Export → [Tab]
  → ExportDialog opens with date range + format options
  → User selects format, optionally adjusts date range
  → Clicks Export → file dialog (asksaveasfilename)
  → App generates file, shows success message
  → On error: specific error message (no broad except)
```

## 15. Domain Types & Enums

A single typed source of truth for every record, shared by models, controllers, views, and tests. No raw dicts crossing layer boundaries.

- `domain/enums.py`: `WorkType` (in_site/road/remote), `VacationType` (annual_leave/public_holiday/unpaid_leave/special_leave/carry_over), `Weekday` (0-6) — all `(str|int, Enum)` so they serialize straight to DB columns.
- `domain/types.py`: `TimeRecord`, `VacationRecord`, `SicknessRecord` — `@dataclass(slots=True)`, always hold real `date`/`time` objects (never strings).
- Models own the only mapping between these dataclasses and SQLite rows (`row_to_record` / `record_to_params`); schema `CHECK(...)` constraints mirror the enum values.

Full enum values, dataclass fields: [design/data-model.md](design/data-model.md) §15.

## 16. Visual Design System

One `theme/style.py` owns all appearance — no view hard-codes colors or fonts. `sv_ttk` is a required dependency, imported unconditionally, providing the modern flat theme with no fallback. Status is always communicated via semantic color tokens (`success`/`warning`/`danger`/`overtime`/`inprogress`) **paired with a text label or icon**, never color alone (accessibility). Typography and spacing pull from a fixed scale; the grouped record list is a single `ttk.Treeview` with per-state tags rather than ad-hoc frames. Dark mode is a single re-style call, persisted in `app_config`.

Full token table, theme-loading code, typography scale, dark-mode details: [design/visual-design.md](design/visual-design.md).

## 17. Application Events (Observer)

tkinter has no signal system, so the §10 "Model emits `data_changed`" is implemented by a tiny synchronous pub/sub bus in `core/events.py`. Decouples models from the views that must refresh.

```
Event enum:   TIME_RECORDS_CHANGED | VACATION_CHANGED | SICKNESS_CHANGED
              | SETTINGS_CHANGED | CLOCK_STATE_CHANGED

EventBus:
  subscribe(event, handler) → unsubscribe token (callable)
  publish(event, **payload) → calls all handlers synchronously
```

Contract:

- One `EventBus` instance created in `main.py`, injected into models, controllers, views.
- Models call `bus.publish(Event.TIME_RECORDS_CHANGED)` after every successful mutation.
- Each tab subscribes on build, **unsubscribes on destroy** (token returned by `subscribe`) to avoid leaks.
- Synchronous + single-threaded (matches tkinter's loop) → no thread-safety concerns. The 60s auto-refresh `root.after` callback simply calls the same refresh handler.

## 18. Time Semantics, DST & Running Balance

All wall-clock handling (`start_time`/`end_time`, duration, overnight wrap) lives in `core/timeutil.py`; the running overtime balance lives in `core/balance.py`. Key points: times are naive local wall-clock, never UTC (UTC is reserved for `created_at`/`updated_at`); display dates use `dd/mm/yyyy` via `to_display_date()`; duration is wall-clock minute arithmetic, so it has a documented, accepted discrepancy on DST spring-forward/fall-back days; the running balance `period_balance(period) = Σ(worked − target)` is a pure function over week/month/year.

Full formulas, DST worked examples, `period_balance` signature: [design/time-and-balance.md](design/time-and-balance.md).

## 19. Controllers

Resolves the §10 references to `Controller.save_record` (previously undefined). Controllers are the only thing views talk to for mutations; they orchestrate validation → model → events.

```
TimeClockController:
  save_record(draft: TimeRecord) → Result(ok, errors)
  clock_in(work_type=None)       → Result
  clock_out()                     → Result
  delete_record(record_id)        → Result

VacationController:
  save_record(draft: VacationRecord) → Result
  add_carry_over(from_year, to_year, hours) → Result

SicknessController:
  save_record(draft: SicknessRecord) → Result
```

- `validate_*` functions live beside each controller and are **pure** (record + context → error list) so §5.6 / §6.5 / §7.3 tables are enforced in one tested place, independent of any dialog.
- `Result` is a small `@dataclass(frozen=True)(ok: bool, errors: tuple[str, ...], warnings: tuple[str, ...])` — no exceptions for expected validation failures; exceptions reserved for true faults (DB error). Frozen so the `ok=False ⟺ errors non-empty` invariant can't be broken post-construction.
- `DatabaseErrorGuard` (`controllers/time_clock_controller.py`) is the shared exception → `Result` translation used by every controller mutation, covering both `sqlite3.Error` and `RecordNotFoundError`. `RecordNotFoundError` (`models/errors.py`, deliberately *not* a `sqlite3.Error` subclass — kept disjoint so a bare `except sqlite3.Error` elsewhere can never silently reclassify it as a real DB failure) is what `update_record()`/`delete_record()` raise when the row affected is zero — an expected stale-record race (double-click delete, stale UI), not a true DB fault. Raising an exception here is deliberate control flow, not an exception to the "no exceptions for expected failures" rule in the line above: the guard catches it and translates it into `Result(ok=False, errors=("RECORD_NOT_FOUND",))` — the machine-readable `WarningCode.RECORD_NOT_FOUND` code, following the same pattern as `OVER_BALANCE_WARNING` — instead of the generic "Database error" message, so no exception ever escapes to callers. Views match on the code and own the user-facing wording: they inform the user, reload the tab's data so the phantom row disappears, and close any open edit dialog (its save can never succeed).
- Views render `Result.errors`; they never re-implement validation.

## 20. Testing

Tests are a first-class deliverable, run with `pytest`. Target ≥ 90% coverage on `core/`, `models/`, `controllers/`, using an in-memory SQLite fixture and an injected `clock` callable (never call `datetime.now()` directly in logic). GUI is smoke-tested only — the logic-heavy layers are testable without one. Priority order: `timeutil` duration/overnight/DST → `balance` running totals → validation tables (one parametrized test per rule) → model CRUD → carry-over auditability → migrations.

Full fixtures, test layout, examples, CI hook: [design/testing.md](design/testing.md).

## 21. Additional v1 Features

The following were originally deferred but are now in scope for v1. Full specs: [design/v1-features.md](design/v1-features.md).

- **§21.1 Public Holidays Auto-Import** — `holidays` library populates `work_day_exception` rows per region/year (incl. Israel/Jewish holidays); existing exceptions are never overwritten.
- **§21.2 Reports (PDF)** — formatted period summary (Month/Quarter/Year), distinct from raw Export §14, via `reportlab`.
- **§21.3 Overtime Tracking (rate)** — configurable multiplier applied to positive running balance only.
- **§21.4 Tray Icon** — `pystray` quick clock in/out; a required dependency, imported unconditionally (no fallback if missing); all actions marshalled to the tkinter thread.
- **§21.5 Break Presets** — quick-set buttons (`15m/30m/45m/1h`) in the time record dialog; view-layer only.
- **§21.6 Week / Month View Toggle** — segmented control on the Time Clock tab; both views share one `Treeview`.
- **§21.7 Hebrew Calendar Date Display** — `hdate` is a required dependency; Hebrew date always shown, never a setting.

## 22. Future Considerations (non-goal for v1)

- Multi-user / sync (LAN or cloud)
