# Time Clock Application — Design Document

## 1. Technology Stack

| Layer | Choice | Rationale |
|---|---|---|
| Language | Python 3.14+ | User requirement |
| GUI Framework | tkinter + ttk (stdlib) + tkcalendar | Stdlib, no deps for core UI; tkcalendar for date picker |
| Theme | `sv-ttk` (optional, bundled fallback) | Modern flat light/dark ttk theme; degrades to stock `clam` if absent (see §16) |
| Data Persistence | SQLite via sqlite3 (stdlib) | Local, single-file, no setup |
| Domain Layer | `@dataclass` + `enum.Enum` (stdlib) | Typed records, no ORM; one source of truth for fields (see §15) |
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

```sql
-- Daily work-hour targets (Settings → Time Clock)
CREATE TABLE work_day_target (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    day_of_week INTEGER NOT NULL CHECK(day_of_week BETWEEN 0 AND 6),
    hours       REAL    NOT NULL CHECK(hours >= 0),
    UNIQUE(day_of_week)
);

-- Date-specific overrides for work-hour targets
-- Takes priority over work_day_target for matching dates
CREATE TABLE work_day_exception (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    date        TEXT    NOT NULL,   -- ISO 8601: YYYY-MM-DD
    hours       REAL    NOT NULL CHECK(hours >= 0),
    label       TEXT,               -- e.g. "Christmas Eve", "Public Holiday"
    UNIQUE(date)
);

-- Time clock records
CREATE TABLE time_record (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    date          TEXT    NOT NULL,   -- ISO 8601: YYYY-MM-DD
    start_time    TEXT    NOT NULL,   -- HH:MM
    end_time      TEXT    DEFAULT NULL,   -- HH:MM, NULL = clocked in, not yet out
    break_minutes INTEGER NOT NULL DEFAULT 0,  -- unpaid break in minutes
    work_type     TEXT    NOT NULL CHECK(work_type IN ('in_site', 'road', 'remote')),
    office        TEXT,               -- office name when work_type = 'in_site'
    note          TEXT,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_time_record_date ON time_record(date);

-- Vacation settings keyed by year (supports contract changes)
CREATE TABLE vacation_settings (
    year             INTEGER PRIMARY KEY, -- e.g., 2025, 2026
    hours_per_year   REAL NOT NULL CHECK(hours_per_year >= 0),
    max_carry_over   REAL NOT NULL CHECK(max_carry_over >= 0)
);

-- Vacation records
CREATE TABLE vacation_record (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    date        TEXT    NOT NULL,   -- ISO 8601
    hours       REAL    NOT NULL CHECK(hours > 0),
    vtype       TEXT    NOT NULL CHECK(vtype IN ('annual_leave', 'public_holiday', 'unpaid_leave', 'special_leave', 'carry_over')),
    note        TEXT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_vacation_record_date ON vacation_record(date);

-- Sickness settings keyed by year (supports allowance changes)
CREATE TABLE sickness_settings (
    year             INTEGER PRIMARY KEY, -- e.g., 2025, 2026
    days_per_year    REAL NOT NULL CHECK(days_per_year >= 0)
);

-- Sickness records
CREATE TABLE sickness_record (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    date        TEXT    NOT NULL,   -- ISO 8601
    hours       REAL    NOT NULL CHECK(hours > 0),
    note        TEXT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_sickness_record_date ON sickness_record(date);

-- Carry-over log: tracks hours transferred between years
-- Each row = one transfer operation. References the source year
-- and destination year so totals are auditable.
CREATE TABLE carry_over_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    from_year       INTEGER NOT NULL,
    to_year         INTEGER NOT NULL,
    hours           REAL    NOT NULL CHECK(hours > 0),
    transferred_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Centralized Settings Table (replaces JSON settings files)
CREATE TABLE app_config (
    key             TEXT PRIMARY KEY,
    value           TEXT NOT NULL -- JSON-serialized configuration/settings values
);
```

### 3.1 Duration Calculation

```
net_duration = (end_time - start_time) - break_minutes

Example:
  start=09:00, end=17:00, break=30min  →  7.5h net
  start=08:30, end=12:00, break=0      →  3.5h net
```

Stored as computed value on read — not persisted. DB stores raw start/end/break.

> **Time semantics (important).** `start_time`/`end_time` are **wall-clock local** `HH:MM`. The schema default `datetime('now')` returns **UTC**, so it is used **only** for the audit columns `created_at`/`updated_at`, never for `start_time`/`end_time`. "Now" for clock-in/out comes from `datetime.now().strftime('%H:%M')` (local). See §18 for DST and overnight handling.

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
- Hebrew date display depends on `hdate` library (optional dep; see §21.7). If absent, Hebrew date portion of day header is omitted silently.

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

- Hebrew Date column populated by `core/hebrew_date.py` (see §21.7). Column hidden if `hdate` unavailable.

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

- Hebrew Date column populated by `core/hebrew_date.py` (see §21.7). Column hidden if `hdate` unavailable.

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
- Display both hours and day-equivalent: "20.0h (2.5 days)"
- Day-equivalent uses `daily_target` from `work_day_target` for the day's day-of-week; fallback to 8h if no target set
- If `daily_target` = 0 (e.g., Saturday off), cap sick day-equivalent at 1 day max (full day sick regardless of target)
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

### 10.1 Time Clock — Add Record

```
User clicks [+ Add Record]
  → TimeRecordDialog opens (pre-filled with today, now)
  → User fills form, clicks Save
  → Dialog validates (see §5.6)
  → Controller.save_record(model_data)
    → Model validates business rules (no overlap)
    → DB insert
    → Model emits data_changed signal
      → Tab's table view refreshes
      → Remaining-today indicator recalculates
```

### 10.2 Vacation Usage Calculation

```
On tab load & after any mutation:
  1. Read vacation_settings for current year Y:
     SELECT hours_per_year FROM vacation_settings WHERE year = Y
  2. SELECT SUM(hours) FROM vacation_record
     WHERE date BETWEEN 'Y-01-01' AND 'Y-12-31'
     AND vtype IN ('annual_leave', 'public_holiday', 'special_leave')
     (this represents used debits X)
  3. SELECT SUM(hours) FROM vacation_record
     WHERE date BETWEEN 'Y-01-01' AND 'Y-12-31'
     AND vtype = 'carry_over'
     (this represents carry-over credit C)
  4. Total pool = Y_allowance + C
  5. Available = Total pool - X
  6. Display "X.Xh / Total pool available" (Remaining: Available)
  7. Compute carry-over from prev year:
     a. prev_year_allowance = SELECT hours_per_year FROM vacation_settings WHERE year = Y-1
     b. prev_year_carry_over = SELECT SUM(hours) FROM vacation_record WHERE date LIKE 'Y-1-%' AND vtype = 'carry_over'
     c. prev_year_used = SELECT SUM(hours) FROM vacation_record WHERE date LIKE 'Y-1-%' AND vtype IN ('annual_leave', 'public_holiday', 'special_leave')
     d. surplus = prev_year_allowance + prev_year_carry_over - prev_year_used
     e. already_transferred = SUM(hours) FROM carry_over_log WHERE from_year = Y-1, to_year = Y
     f. available = MIN(max_carry_over_for_Y, surplus - already_transferred)
```

### 10.3 Vacation — Add Carry-Over

```
User clicks [+ Add Carry-Over Hours]
  → CarryOverDialog opens
  → Dialog queries DB for prev year surplus and already_transferred
  → User enters hours, clicks Add
  → Validation: hours <= available carry-over
  → Transaction:
    1. INSERT INTO carry_over_log (from_year, to_year, hours)
    2. INSERT INTO vacation_record (date, hours, vtype='carry_over', note='Carry-over from YYYY')
   → Tab refreshes
```

### 10.4 Clock-In

```
User clicks [▶ Clock In]
  → If open record exists: prompt "Open record exists. Clock out first or start new?"
    → User chooses "Start new" → proceed
    → User chooses "Cancel" → abort
  → Model checks last-used work_type from settings (default: remote)
  → INSERT INTO time_record (date, start_time, end_time=NULL, work_type, office, note)
  → Tab refreshes, Clock In disables, Clock Out enables
  → root.after(60000, auto_refresh) starts
```

### 10.5 Clock-Out

```
User clicks [■ Clock Out]
  → Model finds today's record(s) WHERE end_time IS NULL
  → If multiple: prompt user to select which record to close
  → If one: close it directly
  → Sets end_time = now
  → UPDATE time_record SET end_time = ? WHERE id = ?
  → Tab refreshes, remaining indicator recalculates
  → If no more open records, cancel auto-refresh timer
```

### 10.6 Sickness Usage Calculation

```
On tab load & after any mutation:
  1. Read sickness_settings for current year Y:
     SELECT days_per_year FROM sickness_settings WHERE year = Y
  2. SELECT SUM(hours) FROM sickness_record
     WHERE date BETWEEN 'Y-01-01' AND 'Y-12-31'
  3. Convert hours → days: divide by daily_target for each record's day-of-week
     (fallback 8h if no target set)
  4. Display "X.X days / Y.Y days used"
  5. Remaining = days_per_year - used_days
```

## 11. File Structure

```
time-clock/
├── main.py                     # Entry point: wires Database → Models → Controllers → Views
├── DESIGN.md                   # This document
├── requirements.txt            # tkcalendar, sv-ttk, holidays, reportlab, pystray, Pillow — all optional / graceful
├── tray.py                     # System-tray icon + quick clock in/out (§21.4), started from main.py
├── settings.py                 # Settings manager (reads/writes using DB app_config table)
├── domain/
│   ├── types.py                # @dataclass records: TimeRecord, VacationRecord, SicknessRecord (§15)
│   └── enums.py                # WorkType, VacationType, Weekday (§15)
├── core/
│   ├── events.py               # EventBus + Event enum — Observer mechanism (§17)
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

Declared in `domain/enums.py` and `domain/types.py`:

```
Enums:
  WorkType      = IN_SITE | ROAD | REMOTE                                               (str enum → DB text)
  VacationType  = ANNUAL_LEAVE | PUBLIC_HOLIDAY | UNPAID_LEAVE | SPECIAL_LEAVE | CARRY_OVER (str enum → DB text)
  Weekday       = MON..SUN (0..6)                                                       (int enum → DB int)

Dataclasses (slots=True):
  TimeRecord:      id, date, start, end | None, break_minutes, work_type, office?, note?
                   .is_open → bool (end is None)

  VacationRecord:  id, date, hours, vtype, note?

  SicknessRecord:  id, date, hours, note?
```

- `(str, Enum)` / `(int, Enum)` values serialize straight to DB columns and round-trip cleanly.
- Models own the only mapping between these dataclasses and SQLite rows (`row_to_record` / `record_to_params`). Schema `CHECK(...)` on each column mirrors the Python enum values.
- `str`/`date`/`time` ↔ ISO conversion centralized in `core/timeutil.py`; dataclasses always hold real `date`/`time`, never strings.

## 16. Visual Design System

Goal: kill the "stock Tk" look. One `theme/style.py` owns all appearance; no view hard-codes colors or fonts.

### 16.1 Theme loading (graceful)

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

### 16.2 Semantic color tokens

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

### 16.3 Typography & spacing

- Fonts: UI `Segoe UI`/`Helvetica` 10pt; numeric totals tabular 11pt **bold**; monospace (`Consolas`) for time columns so `09:00–17:00` aligns.
- Spacing scale (px): `4, 8, 12, 16, 24`. All `padding`/`pady`/`padx` pick from this scale — no arbitrary values.
- Named ttk styles: `Accent.TButton` (primary), `Danger.TButton` (clock-out/delete), `Card.TFrame`, `DayHeader.TLabel`, `Total.TLabel`.

### 16.4 Custom-drawn elements

- Clock In/Out are large `Accent.TButton`/`Danger.TButton` with leading glyphs (▶ / ■).
- Grouped record list uses a `ttk.Treeview` with `tag_configure` per state (`open`, `selected`, `overtime`) rather than ad-hoc frames — gives native selection, keyboard nav, and column sorting for free.
- Optional toolbar icons from `resources/icons/` (16px PNG); absent icons degrade to text labels.

### 16.5 Dark mode

- Toggle in Settings + respect OS preference where detectable. Persisted in database via the `app_config` table (`"theme": "light"|"dark"|"system"`).
- All views read tokens, so dark mode is a single `apply_theme(root, "dark")` re-style + Treeview tag refresh.

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

Centralizes every "what time is it / how long was that" decision so it is testable in isolation (`core/timeutil.py`, `core/balance.py`).

### 18.1 Local time, no UTC for wall-clock

- `now_hm() -> str` returns `datetime.now().strftime("%H:%M")` (local). Used by clock-in/out.
- All `start_time`/`end_time` are naive local wall-clock; the app is single-user single-timezone. UTC is reserved for `created_at`/`updated_at` audit columns only.
- **Display date format**: all Gregorian dates shown to the user use `dd/mm/yyyy` (e.g., `26/06/2026`). Storage in DB and internal Python `date` objects remain ISO 8601 (`YYYY-MM-DD`). Conversion lives in `core/timeutil.py` as `to_display_date(d: date) -> str` (returns `d.strftime("%d/%m/%Y")`). No view or model formats dates directly.

### 18.2 Duration & overnight (DST-aware)

- Duration uses **wall-clock minute arithmetic**, not absolute timestamps, so it is unaffected by DST shifts on normal same-day shifts: `mins(end) - mins(start) - break`.
- Overnight (`end < start`): `(1440 - mins(start)) + mins(end) - break`.
- **DST caveat**: on "spring forward" day (23h) a wall-clock shift e.g. 08:00–17:00 with 1h break reports **7h** (not 8h) because the wall-clock day is only 23h long. On "fall back" day (25h) the same shift reports **9h**. v1 accepts this — single user, rare, documented in `timeutil.duration()` unit test pinning the behavior. Future v2 should use UTC for diff and convert to local for display.

### 18.3 Running overtime balance (new capability)

Per-day "remaining" (§5.4) is good but users care about the cumulative balance. Add:

```
period_balance(period) = Σ over days in period of (worked − target)
```

- Shown in the Time Clock header: `This week: +2.5h  |  This month: −1.0h`.
- Pure function over already-fetched records + targets → no DB coupling, trivially unit-testable.
- Period selector: Week / Month / Year. Computed in `core/balance.py`, surfaced by the controller.

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
- `Result` is a small `@dataclass(ok: bool, errors: list[str])` — no exceptions for expected validation failures; exceptions reserved for true faults (DB error).
- Views render `Result.errors`; they never re-implement validation.

## 20. Testing

Tests are a first-class deliverable, run with `pytest`. The layered/typed design above makes the logic-heavy parts testable **without a GUI**.

### 20.1 Strategy & tooling

| Concern | Tool | Notes |
|---|---|---|
| Test runner | `pytest` | `tests/` mirrors source tree |
| Coverage | `pytest-cov` | Target ≥ 90% on `core/`, `models/`, `controllers/`, validation |
| DB isolation | in-memory SQLite (`:memory:`) | Fresh schema per test via a `db` fixture |
| Time control | inject a `clock` callable | Pass `now` into controllers/timeutil; never call `datetime.now()` directly in logic |
| GUI | **not** unit-tested broadly | Smoke test only (§20.4); logic lives outside views by design |

### 20.2 What gets unit tested (priority order)

1. **`core/timeutil.py`** — duration (same-day, zero-length, break-exceeds-shift), overnight wrap, documented DST behavior, ISO ↔ `date`/`time` round-trip.
2. **`core/balance.py`** — per-day remaining, week/month/year running balance, overtime sign, "no target" path.
3. **Validation functions** — every row of the §5.6 / §6.5 / §7.3 tables = one parametrized test (valid + each failure mode), incl. overlap and overnight-vs-overlap interaction.
4. **Models** (CRUD on `:memory:` DB) — insert/update/delete, open-record queries, monthly grouping/sorting, vacation/sickness yearly sums.
5. **Carry-over logic** — surplus calc, `max_carry_over` clamp, double-transfer prevention (§10.2/§10.3), `carry_over_log` auditability.
6. **Migrations** — `PRAGMA user_version` upgrade path applies cleanly to an old DB fixture.

### 20.3 Fixtures (`tests/conftest.py`)

```python
@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    apply_schema(conn)            # same DDL as production
    yield Database(conn)
    conn.close()

@pytest.fixture
def fixed_clock():
    return lambda: datetime(2026, 6, 26, 9, 0)   # deterministic "now"
```

### 20.4 Layout & example

```
tests/
├── conftest.py
├── core/
│   ├── test_timeutil.py
│   └── test_balance.py
├── models/
│   ├── test_time_clock_model.py
│   ├── test_vacation_model.py     # incl. carry-over
│   └── test_sickness_model.py
├── controllers/
│   └── test_time_clock_controller.py
└── validation/
    └── test_time_record_validation.py
```

```python
# tests/core/test_timeutil.py
import pytest
from core.timeutil import duration

@pytest.mark.parametrize("start,end,brk,expected", [
    ("09:00", "17:00", 30, 7.5),   # normal
    ("08:30", "12:00", 0,  3.5),   # no break
    ("22:00", "06:00", 0,  8.0),   # overnight wrap
    ("09:00", "09:00", 0,  0.0),   # zero-length
])
def test_duration(start, end, brk, expected):
    assert duration(start, end, brk) == pytest.approx(expected)

def test_break_exceeds_shift_is_negative():
    assert duration("09:00", "10:00", 90) < 0   # caller blocks save (§12 #5)
```

### 20.5 CI hook (optional)

- `pytest -q --cov` runnable locally and in CI; `mypy --strict` on `domain/`, `core/`, `controllers/` as a second gate.
- Tests must pass before PyInstaller packaging.

## 21. Additional v1 Features

The following were originally deferred but are now in scope for v1.

### 21.1 Public Holidays Auto-Import

- Settings → Time Clock gains a **Country/Region** selector (default: none) and an **"Import holidays for year"** button.
- Uses the `holidays` library (optional dep; button disabled with hint if missing) to enumerate public holidays for the chosen region + year.
- Each holiday becomes a `work_day_exception` row with `hours = 0` and `label = <holiday name>` — reusing the existing exception mechanism (§3, §5.4). No new table.
- Conflict handling: respects `UNIQUE(date)` — existing exception on a date is **kept**, import skips it and reports "N added, M skipped (already set)".
- Holidays therefore flow automatically into the daily-target logic (0h target ⇒ "Day off") and into the sickness day-equivalent rules.
- **Jewish/Israeli holidays**: when country is set to `IL` (Israel) or `JewishHolidays` locale is selected, the `holidays` library's Israel support is used. This includes Rosh Hashana, Yom Kippur, Sukkot, Passover, Shavuot, Independence Day, etc. These are imported as `work_day_exception` rows exactly like any other country's holidays.
- Country/Region is **optional** — app functions fully without it. Selector defaults to blank ("None"); no import is attempted until a region is chosen.

### 21.2 Reports (PDF summary)

- New **`File → Reports`** menu (distinct from raw Export §14): generates a formatted summary PDF, not a data dump.
- Period selector: **Month / Quarter / Year** + year picker.
- Content: worked vs target totals, running overtime balance (§18.3), vacation used/remaining + carry-over, sickness used/remaining, per-month breakdown table.
- Engine: `reportlab` (same optional dep as PDF export); shares table-styling helpers with §14. Graceful "install reportlab" prompt if absent.
- Implemented in `views/report_dialog.py` + `core/report.py` (pure data assembly → testable without PDF rendering).

### 21.3 Overtime Tracking (configurable rate)

- Builds directly on the running balance (§18.3).
- Settings → Time Clock: **overtime rate** (multiplier, default `1.0`) and **balance period** (week/month/year, default month).
- `core/balance.py` exposes `overtime(period) → (raw_hours, weighted_hours)` where `weighted = raw × rate` for positive balance.
- Header + Reports show both: `Overtime: +5.0h (×1.5 = 7.5h)`. Rate only applies to surplus; deficit shown raw.
- Pure function, covered by §20.2 tests (add rate cases).

### 21.4 Tray Icon + Quick Clock-In/Out

- Optional dep `pystray` (+ `Pillow`); if missing, feature silently disabled, app runs normally.
- Tray icon reflects clock state via color (uses `success`/`fg.muted` tokens, §16.2): active = green, idle = grey.
- Right-click menu: **Clock In**, **Clock Out**, **Open**, **Quit**. Menu items call the same `TimeClockController.clock_in/clock_out` (§19) — no logic duplication.
- Tray actions publish `CLOCK_STATE_CHANGED` (§17) so the main window stays in sync if open.
- Setting: **"Minimize to tray"** (default off) — window close → hide to tray instead of exit when enabled.
- Lives in `tray.py`, started from `main.py` only when the deps + setting allow.
- **Thread Safety & DB Concurrency**: Because the system tray run-loop executes on a separate thread, all actions that invoke controller methods or touch the database must be marshalled back to the main tkinter thread (e.g., using `root.after()` or `root.event_generate()`) to avoid SQLite concurrency violations. Database connections should utilize WAL mode.

### 21.5 Break Presets

- Add/Edit Time Record dialog (§5.5) gains quick-set buttons next to the Break field: **`[15m] [30m] [45m] [1h]`** plus the existing manual `HH:MM` entry.
- Clicking a preset sets the field and re-runs the live net-duration calc. Purely a view-layer convenience; no model/schema change.
- Preset list configurable in Settings (defaults above), stored in the `app_config` table (§3).

### 21.6 Week / Month View Toggle

- Time Clock tab header gains a segmented control: **`[ Week | Month ]`** (default Month, persisted in the `app_config` table).
- **Month view**: existing grouped-by-day display (§5.3).
- **Week view**: 7-day strip (Mon–Sun) for the selected week with prev/next-week nav; each day shows its records + daily subtotal and target delta; week footer shows the §18.3 weekly running balance.
- Both views share the same `ttk.Treeview` and tag styling (§16.4); the toggle swaps the grouping/query, not the widget.
- Week navigation reuses Year/Month filter state; selecting a day in week view scrolls month view to it and vice-versa.

### 21.7 Hebrew Calendar Date Display

Entirely optional — app functions identically without it.

- **Dependency**: `hdate` (PyPI: `hdate`). If not installed, all Hebrew date columns/labels are silently hidden; no warning shown.
- **Conversion utility**: `core/hebrew_date.py` — single function `to_hebrew_label(d: date) -> str | None` that returns a formatted Hebrew date string (e.g., `"י"ז סיוון תשפ"ו"`) or `None` if `hdate` is unavailable.
- **Display locations**:
  - Time Clock grouped list day headers: `── Monday, June 1 / י"ז סיוון תשפ"ו (7.5h) ──`
  - Vacation list: "Hebrew Date" column next to "Date" column
  - Sickness list: "Hebrew Date" column next to "Date" column
  - Export: optional "Hebrew Date" column in CSV/Excel/PDF (checkbox in export dialog, hidden if dep missing)
- **Column width**: fixed monospace-aligned column; uses the same `Consolas` font as time columns (§16.3).
- **Settings toggle**: Settings → General → "Show Hebrew dates" checkbox (default: on when `hdate` is installed, irrelevant when absent). Stored in `app_config`.
- **No schema change**: Hebrew dates are always computed on the fly from the stored Gregorian ISO date. Never persisted.

```python
# core/hebrew_date.py
def to_hebrew_label(d: date) -> str | None:
    try:
        from hdate import HDate
        return str(HDate(d))
    except ImportError:
        return None
```

## 22. Future Considerations (non-goal for v1)

- Multi-user / sync (LAN or cloud)
