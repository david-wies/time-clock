# Time Semantics, DST & Running Balance

> Detail doc for [DESIGN.md](../DESIGN.md) §18 (Time Semantics, DST & Running Balance).

Centralizes every "what time is it / how long was that" decision so it is testable in isolation (`core/timeutil.py`, `core/balance.py`).

## 18.1 Local time, no UTC for wall-clock

- `now_hm() -> str` returns `datetime.now().strftime("%H:%M")` (local). Used by clock-in/out.
- All `start_time`/`end_time` are naive local wall-clock; the app is single-user single-timezone. UTC is reserved for `created_at`/`updated_at` audit columns only.
- **Display date format**: all Gregorian dates shown to the user use `dd/mm/yyyy` (e.g., `26/06/2026`). Storage in DB and internal Python `date` objects remain ISO 8601 (`YYYY-MM-DD`). Conversion lives in `core/timeutil.py` as `to_display_date(d: date) -> str` (returns `d.strftime("%d/%m/%Y")`). No view or model formats dates directly.

## 18.2 Duration & overnight (DST-aware)

- Duration uses **wall-clock minute arithmetic**, not absolute timestamps, so it is unaffected by DST shifts on normal same-day shifts: `mins(end) - mins(start) - break`.
- Overnight (`end < start`): `(1440 - mins(start)) + mins(end) - break`.
- **DST caveat**: on "spring forward" day (23h) a wall-clock shift e.g. 08:00–17:00 with 1h break reports **7h** (not 8h) because the wall-clock day is only 23h long. On "fall back" day (25h) the same shift reports **9h**. v1 accepts this — single user, rare, documented in `timeutil.duration()` unit test pinning the behavior. Future v2 should use UTC for diff and convert to local for display.

## 18.3 Running overtime balance (new capability)

Per-day "remaining" (DESIGN.md §5.4) is good but users care about the cumulative balance. Add:

```
period_balance(period) = Σ over days in period of (worked − target)
```

- Shown in the Time Clock header: `This week: +2.5h  |  This month: −1.0h`.
- Pure function over already-fetched records + targets → no DB coupling, trivially unit-testable.
- Period selector: Week / Month / Year. Computed in `core/balance.py`, surfaced by the controller.
