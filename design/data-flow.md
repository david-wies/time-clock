# Data Flow — Full Sequences

> Detail doc for [DESIGN.md](../DESIGN.md) §10 (Data Flow). Each sequence below
> is View → Controller → Model → DB → EventBus → View refresh.

## 10.1 Time Clock — Add Record

```text
User clicks [+ Add Record]
  → TimeRecordDialog opens (pre-filled with today, now)
  → User fills form, clicks Save
  → Dialog validates (see DESIGN.md §5.6)
  → Controller.save_record(model_data)
    → Model validates business rules (no overlap)
    → DB insert
    → Model emits data_changed signal
      → Tab's table view refreshes
      → Remaining-today indicator recalculates
```

## 10.2 Vacation Usage Calculation

```text
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
      d. surplus = max(0, prev_year_allowance + prev_year_carry_over - prev_year_used)   # clamped to 0
      e. already_transferred = SUM(hours) FROM carry_over_log WHERE from_year = Y-1, to_year = Y
      f. surplus_after_transfer = max(0, surplus - already_transferred)                   # clamped to 0
      g. available = max(0, MIN(max_carry_over_for_Y, surplus_after_transfer))            # clamped to 0
```

## 10.3 Vacation — Add Carry-Over

```text
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

## 10.4 Clock-In

```text
User clicks [▶ Clock In]
  → If open record exists: prompt "Open record exists. Clock out first or start new?"
    → User chooses "Start new" → proceed
    → User chooses "Cancel" → abort
  → Model checks last-used work_type from settings (default: remote)
  → INSERT INTO time_record (date, start_time, end_time=NULL, work_type, office, note)
  → Tab refreshes, Clock In disables, Clock Out enables
  → root.after(60000, auto_refresh) starts
```

## 10.5 Clock-Out

```text
User clicks [■ Clock Out]
  → Model finds today's record(s) WHERE end_time IS NULL
  → If multiple: prompt user to select which record to close
  → If one: close it directly
  → Sets end_time = now
  → UPDATE time_record SET end_time = ? WHERE id = ?
  → Tab refreshes, remaining indicator recalculates
  → If no more open records, cancel auto-refresh timer
```

## 10.6 Sickness Usage Calculation

```text
On tab load & after any mutation:
  1. Read sickness_settings for current year Y:
     SELECT hours_per_year FROM sickness_settings WHERE year = Y
     (no row for Y → allowance defaults to 80.0h, i.e. 10 days × 8h)
  2. SELECT SUM(hours) FROM sickness_record
     WHERE date BETWEEN 'Y-01-01' AND 'Y-12-31'
     (this is used_hours)
  3. remaining_hours = allowance_hours - used_hours
  4. Display "X.Xh / Y.Yh used" (SicknessSummary: allowance_hours, used_hours,
     remaining_hours — see models/sickness_model.py:calculate_sickness_summary())
```

Purely hours-based — there is no day-equivalent conversion anywhere in this
calculation.
