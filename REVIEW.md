# Code Review — Time Clock App

Date: 2026-06-29  
Scope: Full project review, code vs DESIGN.md / CLAUDE.md  
Agents: 4 parallel (domain/core/db, models/controllers, views, tests)

---

## Critical Issues (8)

### 1. `SettingsManager.get()` missing `default` parameter
**File:** `settings.py:25`

`SettingsManager.get()` signature is `def get(self, key: str) -> Any`. CLAUDE.md documents the API as `get(key, default)`. Any caller passing a fallback gets `TypeError`. The current fallback to `self.DEFAULTS.get(key)` silently returns `None` for keys absent from `DEFAULTS` — not equivalent to a caller-supplied default.

**Fix:**
```python
def get(self, key: str, default: Any = None) -> Any:
    ...
    return self.DEFAULTS.get(key, default)
```

---

### 2. `updated_at` never refreshed on UPDATE (all three models)
**Files:** `models/time_clock_model.py:145`, `models/vacation_model.py:89`, `models/sickness_model.py:86`

`DEFAULT (datetime('now'))` in the schema fires only on `INSERT`. Every `UPDATE` statement in all three models omits `updated_at` from the `SET` clause. After the first edit, the audit column permanently holds the insertion timestamp.

**Fix:** Add `updated_at = datetime('now')` to every UPDATE statement:
```sql
UPDATE time_record
SET date = ?, start_time = ?, end_time = ?, break_minutes = ?,
    work_type = ?, office = ?, note = ?,
    updated_at = datetime('now')
WHERE id = ?;
```
Identical fix required in `vacation_model.py` and `sickness_model.py`.

---

### 3. `VacationController.save_record(vtype=CARRY_OVER)` bypasses `carry_over_log`
**File:** `controllers/vacation_controller.py:30-72`

When `save_record()` is called with `vtype=CARRY_OVER`, the balance debit check is skipped (`is_debit` is `False`) and execution falls through to `model.insert_record(record)`, which writes only to `vacation_record`. Nothing is written to `carry_over_log`. The double-transfer guard reads exclusively from `carry_over_log`, so it sees `already_transferred=0` and permits unlimited re-transfers.

**Fix:** Reject `CARRY_OVER` type in `save_record()` — require callers to use `add_carry_over()`:
```python
if record.vtype == VacationType.CARRY_OVER:
    return Result(ok=False, errors=["Use add_carry_over() to record carry-over hours."])
```

---

### 4. `try/except ImportError` + deferred import inside `_do_add`/`_do_edit`
**File:** `views/time_clock_tab.py:742-764`

Both methods contain `try/except ImportError` guards around a deferred `from views.time_record_dialog import TimeRecordDialog`. Violates two CLAUDE.md rules simultaneously: "Imports at file header only" and "No `try/except ImportError` guards." A real import failure (e.g. syntax error in `time_record_dialog.py`) is swallowed and silently replaced with "Time record dialog is not yet available."

**Fix:** Move import to file header, remove try/except blocks.

---

### 5. `SicknessTab` missing Ctrl+E and Delete keyboard shortcuts
**File:** `views/sickness_tab.py`

`_bind_shortcuts` binds only `<Control-Shift-S>` and `<F5>`. DESIGN.md §4.2 specifies Ctrl+E (edit) and Delete (remove) as "All tabs" scope. Both are present in `TimeClockTab` and `VacationTab`.

**Fix:**
```python
self.root.bind_all("<Control-e>", _guard(self._do_edit), add=True)
self.root.bind_all("<Delete>",    _guard(self._do_delete), add=True)
```

---

### 6. EventBus publish not verified for `update_record`/`delete_record` in TimeClockModel tests
**File:** `tests/models/test_time_clock_model.py:28-56`

`change_called` is set to `True` after `insert_record` and never reset. Subsequent `update_record` and `delete_record` calls never re-check the flag. Removing `bus.publish()` from either method would not cause any test to fail.

**Fix:** Reset and assert after each mutation:
```python
change_called = False
model.update_record(fetched)
assert change_called is True

change_called = False
model.delete_record(rec_id)
assert change_called is True
```

---

### 7. Zero EventBus publish verification in VacationModel and SicknessModel tests
**Files:** `tests/models/test_vacation_model.py`, `tests/models/test_sickness_model.py`

Neither file subscribes to `VACATION_CHANGED` or `SICKNESS_CHANGED`. Every insert/update/delete could silently drop `bus.publish()` and all tests would still pass.

**Fix:** Subscribe to the relevant event in each model test file and assert the handler fires after each mutation. Pattern demonstrated in `test_time_record_crud`.

---

### 8. `clock_in(force=True)` branch has zero test coverage
**File:** `tests/controllers/test_time_clock_controller.py:87-89`

`test_clock_in_out_flow` asserts `OPEN_RECORD_EXISTS` on a second clock-in but never calls `clock_in(force=True)`. A regression in the `if open_today and not force` branch in the controller would be invisible.

**Fix:**
```python
res_force = controller.clock_in(force=True)
assert res_force.ok is True
assert len(controller.model.get_open_records()) == 2
```

---

## Important Issues (8)

### 9. `or 1.0` falsy guard silently overrides stored `0.0` overtime rate
**File:** `core/report.py:130`

```python
overtime_rate = float(settings.get("overtime_rate") or 1.0)
```

`0.0` is a valid user-configured value (no overtime compensation), but `0.0 or 1.0` evaluates to `1.0`. Root cause is issue #1 (missing `default` param). Fix both together:
```python
overtime_rate = float(settings.get("overtime_rate", 1.0))
```

---

### 10. Summary dicts cross model→controller boundary (CLAUDE.md violation)
**Files:** `models/vacation_model.py:177,227`, `models/sickness_model.py:169`

`calculate_vacation_summary`, `calculate_carry_over_allowance`, and `calculate_sickness_summary` return `dict[str, float]` consumed directly by controllers via string key access (`summary["remaining"]`, `allowance["allowed_transfer"]`, `summary["used_days"]`). A key rename breaks silently at runtime with `KeyError`, invisible to mypy.

**Fix:** Add typed dataclasses to `domain/types.py`:
```python
@dataclass(slots=True)
class VacationSummary:
    allowance: float
    carry_over: float
    total_pool: float
    used: float
    remaining: float

@dataclass(slots=True)
class CarryOverAllowance:
    prev_surplus: float
    max_carry_over: float
    already_transferred: float
    available_surplus: float
    allowed_transfer: float

@dataclass(slots=True)
class SicknessSummary:
    allowance: float
    used_hours: float
    used_days: float
    remaining_days: float
```

---

### 11. `get_date_exceptions()` and `get_carry_over_history()` return raw `list[dict]`
**Files:** `models/time_clock_model.py:203`, `models/vacation_model.py:151`

Both return record-shaped `list[dict[str, Any]]` that cross the layer boundary with no type-checking. No corresponding domain dataclasses exist in `domain/types.py`.

**Fix:** Add `WorkDayException` and `CarryOverLogEntry` dataclasses to `domain/types.py` and update method return types.

---

### 12. Two `try/except ImportError` guards for `holidays` package inside method bodies
**File:** `views/settings_dialog.py:257-272,310-314`

`_build_tab_timeclock` probes for `holidays` with a try/except to set `hol_available`. `_import_holidays` does the same before calling `holidays.country_holidays()`. Both violate "Imports at file header only" and "No `try/except ImportError` guards." `holidays` is an installed dep.

**Fix:** Move `import holidays` to file header. Remove `hol_available` flag and the "Install holidays package to enable" label. Remove the guard in `_import_holidays`.

---

### 13. Deferred dialog imports inside method bodies
**Files:** `views/vacation_tab.py:369,378,400`, `views/sickness_tab.py:333,342`

`_do_add`, `_do_edit`, and `_do_carry_over` in `vacation_tab.py` import `VacationRecordDialog` and `CarryOverDialog` inside method bodies. `_do_add` and `_do_edit` in `sickness_tab.py` import `SickRecordDialog` inside method bodies. Violates "Imports at file header only."

**Fix:** Move all dialog imports to each file's header.

---

### 14. `_unsub` (unsubscribe token) has zero test coverage
**Location:** No `tests/core/test_events.py` exists

CLAUDE.md mandates unsubscribe on destroy. No test calls the token returned by `subscribe()` or verifies that the handler stops firing afterward.

**Fix:** Create `tests/core/test_events.py`:
```python
def test_unsubscribe_stops_delivery():
    bus = EventBus()
    calls = []
    unsub = bus.subscribe(Event.TIME_RECORDS_CHANGED, lambda: calls.append(1))
    bus.publish(Event.TIME_RECORDS_CHANGED)
    assert calls == [1]
    unsub()
    bus.publish(Event.TIME_RECORDS_CHANGED)
    assert calls == [1]  # no second delivery
```

---

### 15. Edit-path `OVER_BALANCE_WARNING` untested for Vacation and Sickness controllers
**Files:** `tests/controllers/test_vacation_controller.py`, `tests/controllers/test_sickness_controller.py`

Insert-path warning is covered. Edit-path (`record.id is not None`) adjusts `projected_remaining` by subtracting the old record's hours — this branch is untested. A wrong sign or wrong field would silently allow over-draft on edit.

**Fix:** Add a test for each: save a record within balance, fetch it, change hours to exceed balance, assert `OVER_BALANCE_WARNING`, re-call with `confirm_over_balance=True`, assert `ok=True`.

---

### 16. Inline `EventBus()` in sickness controller test violates single-bus rule
**File:** `tests/controllers/test_sickness_controller.py:38`

```python
tc_model = TimeClockModel(controller.model.db, EventBus())
```

Creates a second isolated bus. CLAUDE.md: "One `EventBus` instance created in `main.py`, injected into models, controllers, views." Events published by `tc_model` never reach the fixture's bus.

**Fix:** Request `event_bus` fixture explicitly and pass it through:
```python
def test_save_balance_warning_and_override(controller, event_bus):
    tc_model = TimeClockModel(controller.model.db, event_bus)
```

---

### 17. `VacationModel.get_carry_over_history()` untested
**File:** `tests/models/test_vacation_model.py`

`test_vacation_balance_and_carry_over` verifies carry-over via `get_already_transferred()` and `calculate_vacation_summary()` but never calls `get_carry_over_history()`. A SQL typo in its `WHERE to_year = ?` clause would silently return empty results.

**Fix:**
```python
history = model.get_carry_over_history(2026)
assert len(history) == 1
assert history[0]["hours"] == 15.0
assert history[0]["from_year"] == 2025
```

---

## Passing Checks (no issues)

- DB schema matches DESIGN.md §3 exactly — all tables, constraints, indexes, and defaults correct
- Three `AFTER UPDATE` triggers in `db/database.py` are additive and correct
- `PRAGMA user_version` migration pattern correct
- EventBus contract (§17): `subscribe()` returns `_unsub` callable, `publish()` synchronous — correct
- Overnight shift duration math (`(1440 - start) + end - break`) matches §3.1 and §18.2
- `to_display_date()` used in all views; no view formats dates directly
- UTC discipline: `datetime('now')` only for `created_at`/`updated_at`/`transferred_at`; `datetime.now()` for time entries
- `core/hebrew_date.py` imports `hdate` unconditionally at header — correct
- `get_open_records_for_date()` exists and is used correctly by controller
- EventBus subscribe/unsubscribe tokens present in all three tabs
- 60s auto-refresh for "remaining today" counter implemented correctly
- `main.py` is fully wired (CLAUDE.md note "Phase 7 not started" is stale — update it)
