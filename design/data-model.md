# Data Model — Schema & Domain Types

> Detail doc for [DESIGN.md](../DESIGN.md) §3 (Data Model) and §15 (Domain Types
> & Enums). Read the main doc first for context; this file has the full SQL and
> type definitions.

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
    updated_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    document_path TEXT                -- optional file attachment (PDF, image, etc.)
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
    hours       REAL    NOT NULL CHECK(hours >= 0),
    vtype       TEXT    NOT NULL CHECK(vtype IN ('annual_leave', 'public_holiday', 'unpaid_leave', 'special_leave', 'carry_over')),
    note        TEXT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_vacation_record_date ON vacation_record(date);
```

> **Migration note.** `vacation_record.hours` was originally
> `CHECK(hours > 0)`; a `PRAGMA user_version` migration (db/database.py,
> version 2) relaxed it to `CHECK(hours >= 0)` to allow 0-hour holiday
> imports (e.g. a `public_holiday` row imported for a day that carries no
> hour value). The `sickness_record.hours` and `carry_over_log.hours`
> columns are unaffected and still require `CHECK(hours > 0)`.

```sql
-- Sickness settings keyed by year (supports allowance changes)
CREATE TABLE sickness_settings (
    year             INTEGER PRIMARY KEY, -- e.g., 2025, 2026
    hours_per_year   REAL NOT NULL CHECK(hours_per_year >= 0)
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

-- Miliuim (reserve duty) periods — date-range model. Replaced the earlier
-- per-day miliuim_record + miliuim_settings tables (PRAGMA user_version 6).
CREATE TABLE miliuim_period (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    start_date    TEXT    NOT NULL,
    end_date      TEXT    NOT NULL CHECK(end_date >= start_date),
    note          TEXT,
    document_path TEXT,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_miliuim_period_start ON miliuim_period(start_date);
```

### 3.1 Duration Calculation

```text
net_duration = (end_time - start_time) - break_minutes

Example:
  start=09:00, end=17:00, break=30min  →  7.5h net
  start=08:30, end=12:00, break=0      →  3.5h net
```

Stored as computed value on read — not persisted. DB stores raw start/end/break.

> **Time semantics (important).** `start_time`/`end_time` are **wall-clock
> local** `HH:MM`. The schema default `datetime('now')` returns **UTC**, so it
> is used **only** for the audit columns `created_at`/`updated_at`, never for
> `start_time`/`end_time`. "Now" for clock-in/out is obtained through an
> **injected `now`/`now_hm` callable** rather than a direct call, so tests can
> supply a `fixed_clock` for determinism; the underlying production source is
> local wall-clock `datetime.now().strftime('%H:%M')`. See
> [design/time-and-balance.md](time-and-balance.md) (§18) for the callable
> contract, DST, and overnight handling.

## 15. Domain Types & Enums

A single typed source of truth for every record, shared by models, controllers,
views, and tests. No raw dicts crossing layer boundaries.

Declared in `domain/enums.py` and `domain/types.py`:

```text
Enums:
  WorkType      = IN_SITE | ROAD | REMOTE                                               (str enum → DB text)
  VacationType  = ANNUAL_LEAVE | PUBLIC_HOLIDAY | UNPAID_LEAVE | SPECIAL_LEAVE | CARRY_OVER (str enum → DB text)
  Weekday       = MON..SUN (0..6)                                                       (int enum → DB int)
  WarningCode   = OVERNIGHT_SHIFT_WARNING (blocking=False) | OPEN_RECORD_EXISTS (blocking=True)
                  | MULTIPLE_OPEN_RECORDS (blocking=True) | OVER_BALANCE_WARNING (blocking=True) (str enum → Result.warnings/errors; `blocking` picks which)
  PeriodType    = MONTH | QUARTER | YEAR                                                (str enum → DB text)
  OvertimePeriod = WEEK | MONTH | YEAR                                                  (str enum → DB text)

Dataclasses (slots=True):
  TimeRecord:         id, date, start, end | None, break_minutes, work_type, office?, note?, document_path?
                      .is_open → bool (end is None)

  VacationRecord:     id, date, hours, vtype, note?

  SicknessRecord:     id, date, hours, note?, document_path?

  WorkDayException:   id, date, hours, label?

  CarryOverLogEntry:  id, from_year, to_year, hours, transferred_at

  MiliuimRecord:      id, start_date, end_date, note?, document_path?
  MiliuimSummary:     period_count, total_days

  PeriodBalance:      worked_hours, target_hours, overtime_rate, days_in_period
                      .balance / .weighted_overtime → computed properties
  VacationSummary:    allowance, carry_over, used, remaining, total_pool
  CarryOverAllowance: available, max_carry_over, already_transferred
  SicknessSummary:    used, total_pool, remaining
```

- `(str, Enum)` / `(int, Enum)` values serialize straight to DB columns and
  round-trip cleanly.
- Models own the only mapping between these dataclasses and SQLite rows
  (`row_to_record` / `record_to_params`). Schema `CHECK(...)` on each column
  mirrors the Python enum values.
- `str`/`date`/`time` ↔ ISO conversion centralized in `core/timeutil.py`;
  dataclasses always hold real `date`/`time`, never strings.
