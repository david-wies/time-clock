# Testing Strategy

> Detail doc for [DESIGN.md](../DESIGN.md) §20 (Testing).

Tests are a first-class deliverable, run with `pytest`. The layered/typed design in the main doc makes the logic-heavy parts testable **without a GUI**.

## 20.1 Strategy & tooling

| Concern | Tool | Notes |
|---|---|---|
| Test runner | `pytest` | `tests/` mirrors source tree |
| Coverage | `pytest-cov` | Target ≥ 90% on `core/`, `models/`, `controllers/`, validation |
| DB isolation | in-memory SQLite (`:memory:`) | Fresh schema per test via a `db` fixture |
| Time control | inject a `clock` callable | Pass `now` into controllers/timeutil; never call `datetime.now()` directly in logic |
| GUI | **not** unit-tested broadly | Smoke test only (§20.4); logic lives outside views by design |

## 20.2 What gets unit tested (priority order)

1. **`core/timeutil.py`** — duration (same-day, zero-length, break-exceeds-shift), overnight wrap, documented DST behavior, ISO ↔ `date`/`time` round-trip.
2. **`core/balance.py`** — per-day remaining, week/month/year running balance, overtime sign, "no target" path.
3. **Validation functions** — every row of the DESIGN.md §5.6 / §6.5 / §7.3 tables = one parametrized test (valid + each failure mode), incl. overlap and overnight-vs-overlap interaction.
4. **Models** (CRUD on `:memory:` DB) — insert/update/delete, open-record queries, monthly grouping/sorting, vacation/sickness yearly sums.
5. **Carry-over logic** — surplus calc, `max_carry_over` clamp, double-transfer prevention (see [data-flow.md](data-flow.md) §10.2/§10.3), `carry_over_log` auditability.
6. **Migrations** — `PRAGMA user_version` upgrade path applies cleanly to an old DB fixture.

## 20.3 Fixtures (`tests/conftest.py`)

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

## 20.4 Layout & example

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
    assert duration("09:00", "10:00", 90) < 0   # caller blocks save (DESIGN.md §12 #5)
```

## 20.5 CI hook (optional)

- `pytest -q --cov` runnable locally and in CI; `mypy --strict` on `domain/`, `core/`, `controllers/` as a second gate.
- Tests must pass before PyInstaller packaging.
