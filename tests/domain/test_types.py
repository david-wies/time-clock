"""Tests for domain/types.py's self-enforced, context-free invariants.

Context-dependent rules (overlap checks, live-settings-derived hour caps)
are NOT tested here — they remain controller-level and are covered by
tests/controllers/*.
"""

import dataclasses
import sqlite3
from datetime import date, datetime, time

import pytest

from domain.enums import VacationType, WorkType
from domain.types import (
    BreakMinutes,
    CarryOverLogEntry,
    Hours,
    MiliuimRecord,
    PeriodBalance,
    Result,
    SicknessRecord,
    TimeRecord,
    VacationRecord,
    WorkDayException,
)

# ─────────────────────────── Hours / BreakMinutes ─────────────────────────────


def test_hours_negative_raises() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        Hours(-1)


def test_hours_nan_raises() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        Hours(float("nan"))


def test_hours_infinite_raises() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        Hours(float("inf"))


def test_break_minutes_negative_raises() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        BreakMinutes(-1)


def test_break_minutes_nan_raises() -> None:
    """Mirrors test_hours_nan_raises above: BreakMinutes.__new__ has its own
    `isinstance(value, float) and (math.isnan(value) or math.isinf(value))`
    guard, separate from Hours' -- `int(float("nan"))` would otherwise raise
    a confusing ValueError from the plain `int()` coercion instead of this
    class's own "non-negative" message."""
    with pytest.raises(ValueError, match="non-negative"):
        BreakMinutes(float("nan"))


def test_break_minutes_infinite_raises() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        BreakMinutes(float("inf"))


def test_hours_behaves_as_plain_float_in_arithmetic() -> None:
    h = Hours(8.5)
    assert isinstance(h, float)
    assert h + 1.5 == 10.0
    assert h > Hours(8.0)
    assert h == 8.5


def test_break_minutes_behaves_as_plain_int_in_arithmetic() -> None:
    b = BreakMinutes(30)
    assert isinstance(b, int)
    assert int(b) == 30
    assert b + 15 == 45
    assert b < BreakMinutes(60)


def test_hours_binds_correctly_as_sqlite3_parameter() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE TABLE t (h REAL)")
        conn.execute("INSERT INTO t (h) VALUES (?)", (Hours(8.5),))
        row = conn.execute("SELECT h FROM t").fetchone()
    finally:
        conn.close()
    assert row[0] == 8.5
    assert type(row[0]) is float


def test_break_minutes_binds_correctly_as_sqlite3_parameter() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE TABLE t (b INTEGER)")
        conn.execute("INSERT INTO t (b) VALUES (?)", (BreakMinutes(30),))
        row = conn.execute("SELECT b FROM t").fetchone()
    finally:
        conn.close()
    assert row[0] == 30
    assert type(row[0]) is int


# ─────────────────────────────── TimeRecord ──────────────────────────────────


def _time_record(**overrides) -> TimeRecord:
    defaults = dict(
        id=None,
        date=date(2026, 6, 26),
        start_time=time(9, 0),
        end_time=time(17, 0),
        break_minutes=30,
        work_type=WorkType.REMOTE,
        office=None,
        note=None,
    )
    defaults.update(overrides)
    return TimeRecord(**defaults)


def test_time_record_valid_construction_succeeds() -> None:
    rec = _time_record()
    assert rec.break_minutes == 30


def test_time_record_open_record_with_no_end_time_succeeds() -> None:
    rec = _time_record(end_time=None, break_minutes=0)
    assert rec.is_open is True


def test_time_record_overnight_shift_still_constructs() -> None:
    """Overnight shift (end < start) is a *warning*, not a construction
    error — it must remain constructible so validate_time_record() can
    still surface OVERNIGHT_SHIFT_WARNING as a non-blocking result."""
    rec = _time_record(start_time=time(22, 0), end_time=time(6, 0), break_minutes=0)
    assert rec.start_time == time(22, 0)


def test_time_record_negative_break_minutes_raises() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        _time_record(break_minutes=-1)


def test_time_record_break_exceeding_shift_length_raises() -> None:
    # 09:00-10:00 is 60 minutes; a 75-minute break exceeds it.
    with pytest.raises(ValueError, match="Break cannot exceed shift length"):
        _time_record(start_time=time(9, 0), end_time=time(10, 0), break_minutes=75)


def test_time_record_overnight_break_exceeding_wrapped_duration_raises() -> None:
    """time_record_invariant_errors() must check break_minutes against the
    overnight-*wrapped* duration (core.timeutil.duration(), which adds
    1440 minutes when end < start), not a naive end-minus-start
    subtraction. 22:00->06:00 wraps to a 480-minute (8h) shift; naive
    subtraction would instead see 360-1320 = -960 minutes, under which a
    500-minute break would nonsensically appear to fit. The wrap-aware
    duration correctly rejects it as exceeding the real 8h shift."""
    with pytest.raises(ValueError, match="Break cannot exceed shift length"):
        _time_record(start_time=time(22, 0), end_time=time(6, 0), break_minutes=500)


def test_time_record_overnight_break_within_wrapped_duration_succeeds() -> None:
    """Same overnight 22:00->06:00 shift (480 wrapped minutes) as above, but
    with a 400-minute break that fits comfortably within it -- confirms the
    wrap-aware check isn't simply rejecting every overnight break."""
    rec = _time_record(start_time=time(22, 0), end_time=time(6, 0), break_minutes=400)
    assert rec.break_minutes == 400


def test_time_record_in_site_without_office_raises() -> None:
    with pytest.raises(ValueError, match="select or enter an office"):
        _time_record(work_type=WorkType.IN_SITE, office=None)


def test_time_record_in_site_with_blank_office_raises() -> None:
    with pytest.raises(ValueError, match="select or enter an office"):
        _time_record(work_type=WorkType.IN_SITE, office="   ")


def test_time_record_in_site_with_office_succeeds() -> None:
    rec = _time_record(work_type=WorkType.IN_SITE, office="Main Office")
    assert rec.office == "Main Office"


def test_time_record_note_too_long_raises() -> None:
    with pytest.raises(ValueError, match="Note is too long"):
        _time_record(note="a" * 501)


def test_time_record_note_at_limit_succeeds() -> None:
    rec = _time_record(note="a" * 500)
    assert rec.note is not None and len(rec.note) == 500


def test_time_record_is_frozen() -> None:
    """TimeRecord is immutable: direct field assignment must raise rather
    than silently produce a record whose fields are individually valid but
    jointly invalid (e.g. break_minutes no longer fitting the shift once
    end_time changes). Callers must use dataclasses.replace() instead, which
    reruns __post_init__ in full — see
    test_time_record_replace_reruns_full_validation below and
    controllers.time_clock_controller.TimeClockController.clock_out()."""
    rec = _time_record()

    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.break_minutes = 45  # type: ignore[misc]


def test_time_record_replace_reruns_full_validation() -> None:
    rec = _time_record(start_time=time(9, 0), end_time=time(10, 0), break_minutes=30)

    with pytest.raises(ValueError, match="Break cannot exceed shift length"):
        dataclasses.replace(rec, break_minutes=75)


# ─────────────────────────────── VacationRecord ──────────────────────────────


def test_vacation_record_valid_construction_succeeds() -> None:
    rec = VacationRecord(None, date(2026, 7, 15), 8.0, VacationType.ANNUAL_LEAVE)
    assert rec.hours == 8.0


def test_vacation_record_negative_hours_raises() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        VacationRecord(None, date(2026, 7, 15), -1.0, VacationType.ANNUAL_LEAVE)


def test_vacation_record_note_too_long_raises() -> None:
    with pytest.raises(ValueError, match="Note is too long"):
        VacationRecord(
            None, date(2026, 7, 15), 8.0, VacationType.ANNUAL_LEAVE, note="a" * 501
        )


def test_vacation_record_allows_carry_over_vtype_for_db_readback() -> None:
    """VacationRecord must NOT reject vtype=CARRY_OVER at construction.

    VacationModel.add_carry_over() inserts a 'carry_over' row directly into
    the vacation_record table via raw SQL — it never constructs a
    VacationRecord. But VacationModel._row_to_record() (used by
    get_records_for_year()/get_record_by_id()) reconstructs a VacationRecord
    from every row in that table when reading it back, including carry-over
    rows, and views/vacation_tab.py + views/export_dialog.py both display
    those read-back records. Rejecting CARRY_OVER at construction would
    crash the Vacation tab and CSV/PDF export for any year with a
    carry-over transfer on record.
    """
    rec = VacationRecord(
        None, date(2026, 1, 1), 20.0, VacationType.CARRY_OVER, "Carry-over from 2025"
    )
    assert rec.vtype == VacationType.CARRY_OVER


def test_vacation_record_is_frozen() -> None:
    """VacationRecord is immutable, like TimeRecord — see
    test_time_record_is_frozen above. Callers must use dataclasses.replace()
    instead, which reruns __post_init__ in full — see
    test_vacation_record_replace_reruns_full_validation below."""
    rec = VacationRecord(None, date(2026, 7, 15), 8.0, VacationType.ANNUAL_LEAVE)

    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.hours = 4.0  # type: ignore[misc]


def test_vacation_record_replace_reruns_full_validation() -> None:
    rec = VacationRecord(None, date(2026, 7, 15), 8.0, VacationType.ANNUAL_LEAVE)

    with pytest.raises(ValueError, match="non-negative"):
        dataclasses.replace(rec, hours=-1.0)


# ─────────────────────────────── SicknessRecord ──────────────────────────────


def test_sickness_record_valid_construction_succeeds() -> None:
    rec = SicknessRecord(None, date(2026, 2, 15), 8.0, "Flu")
    assert rec.hours == 8.0


def test_sickness_record_negative_hours_raises() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        SicknessRecord(None, date(2026, 2, 15), -0.5, "Flu")


def test_sickness_record_note_too_long_raises() -> None:
    with pytest.raises(ValueError, match="Note is too long"):
        SicknessRecord(None, date(2026, 2, 15), 8.0, "a" * 501)


def test_sickness_record_is_frozen() -> None:
    """SicknessRecord is immutable, like TimeRecord — see
    test_time_record_is_frozen above."""
    rec = SicknessRecord(None, date(2026, 2, 15), 8.0, "Flu")

    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.hours = 4.0  # type: ignore[misc]


def test_sickness_record_replace_reruns_full_validation() -> None:
    rec = SicknessRecord(None, date(2026, 2, 15), 8.0, "Flu")

    with pytest.raises(ValueError, match="non-negative"):
        dataclasses.replace(rec, hours=-1.0)


# ─────────────────────────────── MiliuimRecord ───────────────────────────────


def test_miliuim_record_valid_construction_succeeds() -> None:
    rec = MiliuimRecord(None, date(2026, 6, 1), date(2026, 6, 10))
    assert rec.start_date == date(2026, 6, 1)


def test_miliuim_record_single_day_period_succeeds() -> None:
    rec = MiliuimRecord(None, date(2026, 6, 22), date(2026, 6, 22))
    assert rec.start_date == rec.end_date


def test_miliuim_record_end_before_start_raises() -> None:
    with pytest.raises(ValueError, match="End date must be on or after start date"):
        MiliuimRecord(None, date(2026, 6, 22), date(2026, 6, 20))


def test_miliuim_record_note_too_long_raises() -> None:
    with pytest.raises(ValueError, match="Note is too long"):
        MiliuimRecord(None, date(2026, 6, 1), date(2026, 6, 5), note="x" * 501)


def test_miliuim_record_is_frozen() -> None:
    """MiliuimRecord is immutable — unlike VacationRecord/SicknessRecord,
    this matters for a genuine cross-field invariant (end_date >=
    start_date): freezing is what makes it impossible to construct a
    MiliuimRecord whose fields are individually fine but jointly invalid
    (e.g. changing only end_date without re-checking it against
    start_date). See test_miliuim_record_replace_reruns_full_validation
    below and MiliuimRecord's docstring (domain/types.py)."""
    rec = MiliuimRecord(None, date(2026, 6, 1), date(2026, 6, 10))

    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.end_date = date(2026, 6, 20)  # type: ignore[misc]


def test_miliuim_record_replace_reruns_full_validation() -> None:
    rec = MiliuimRecord(None, date(2026, 6, 1), date(2026, 6, 10))

    with pytest.raises(ValueError, match="End date must be on or after start date"):
        dataclasses.replace(rec, end_date=date(2026, 5, 20))


# ────────────────────────────── WorkDayException ─────────────────────────────


def test_workday_exception_valid_construction_succeeds() -> None:
    exc = WorkDayException(1, date(2026, 6, 1), 8.0, "Holiday")
    assert exc.hours == 8.0


def test_workday_exception_negative_hours_raises() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        WorkDayException(1, date(2026, 6, 1), -1.0, "Holiday")


def test_workday_exception_nan_hours_raises() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        WorkDayException(1, date(2026, 6, 1), float("nan"), "Holiday")


def test_workday_exception_infinite_hours_raises() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        WorkDayException(1, date(2026, 6, 1), float("inf"), "Holiday")


def test_workday_exception_rejects_negative_hours_after_mutation() -> None:
    """WorkDayException.hours is a _ValidatingRecord-validated field
    (domain/types.py), so mutating it to an invalid value on an
    already-constructed instance raises ValueError immediately, same as at
    construction time — see test_workday_exception_negative_hours_raises."""
    exc = WorkDayException(1, date(2026, 6, 1), 8.0, "Holiday")

    with pytest.raises(ValueError, match="non-negative"):
        exc.hours = -1.0


# ───────────────────────────── CarryOverLogEntry ─────────────────────────────


def test_carry_over_log_entry_valid_construction_succeeds() -> None:
    entry = CarryOverLogEntry(1, 2025, 2026, 5.0, datetime(2026, 1, 1))
    assert entry.hours == 5.0


def test_carry_over_log_entry_non_positive_hours_raises() -> None:
    with pytest.raises(ValueError, match="positive"):
        CarryOverLogEntry(1, 2025, 2026, 0.0, datetime(2026, 1, 1))


def test_carry_over_log_entry_non_consecutive_years_raises() -> None:
    with pytest.raises(ValueError, match="one year after"):
        CarryOverLogEntry(1, 2024, 2026, 5.0, datetime(2026, 1, 1))


def test_carry_over_log_entry_rejects_non_positive_hours_after_mutation() -> None:
    """CarryOverLogEntry.hours is a _ValidatingRecord-validated field
    (domain/types.py), so mutating it to an invalid value on an
    already-constructed instance raises ValueError immediately, same as at
    construction time — see test_carry_over_log_entry_non_positive_hours_raises.

    Uses 0.0 rather than a negative value: _positive_hours() (domain/
    types.py) now delegates the finite/non-negative check to Hours first,
    so a negative value like -1.0 raises Hours' "non-negative" message
    before reaching the positivity check below it. 0.0 is non-negative (so
    it passes Hours) but not positive, so it is the value that specifically
    exercises CarryOverLogEntry's stricter-than-Hours "must be positive"
    requirement — matching test_carry_over_log_entry_non_positive_hours_raises
    at construction time."""
    entry = CarryOverLogEntry(1, 2025, 2026, 5.0, datetime(2026, 1, 1))

    with pytest.raises(ValueError, match="positive"):
        entry.hours = 0.0


# ─────────────────────────────── PeriodBalance ───────────────────────────────


def test_period_balance_fields() -> None:
    """balance is a computed property (domain/types.py), not a constructor
    argument -- it is always worked_hours - target_hours, so it is derived
    rather than passed in. See test_period_balance_balance_is_computed
    below for the property itself."""
    pb = PeriodBalance(
        worked_hours=16.5,
        target_hours=16.0,
        weighted_overtime=0.5,
        days_in_period=2,
    )
    assert pb.worked_hours == 16.5
    assert pb.target_hours == 16.0
    assert pb.balance == 0.5
    assert pb.weighted_overtime == 0.5
    assert pb.days_in_period == 2


def test_period_balance_balance_is_computed() -> None:
    pb = PeriodBalance(
        worked_hours=10.0,
        target_hours=16.0,
        weighted_overtime=-6.0,
        days_in_period=2,
    )
    assert pb.balance == -6.0


# ────────────────────────────────── Result ───────────────────────────────────


def test_result_ok_false_without_errors_raises() -> None:
    with pytest.raises(ValueError, match="must carry at least one error"):
        Result(ok=False)


def test_result_ok_true_with_errors_raises() -> None:
    """The mirror case of test_result_ok_false_without_errors_raises: an
    ok=True Result must not carry errors either, or a caller that only
    checks `if not result.ok` (this codebase's documented pattern) would
    silently drop a real error. See Result's docstring (domain/types.py)."""
    with pytest.raises(ValueError, match="must not carry any errors"):
        Result(ok=True, errors=["should not be constructible"])


def test_result_ok_true_with_warnings_succeeds() -> None:
    """Only errors are constrained by the ok/errors invariant -- warnings
    are allowed (and expected) alongside ok=True."""
    result = Result(ok=True, warnings=["OVERNIGHT_SHIFT_WARNING"])
    assert result.ok is True
    assert result.warnings == ["OVERNIGHT_SHIFT_WARNING"]


# ────────────────────── Dialog-style construction guard ─────────────────────


def test_dialog_style_try_except_around_construction_yields_clean_result() -> None:
    """Mirrors the try/except every record-constructing dialog now wraps
    around its `Record(...)` call (views/time_record_dialog.py,
    views/vacation_record_dialog.py, views/sick_record_dialog.py,
    views/miliuim_record_dialog.py): a ValueError raised by __post_init__
    must translate into an ordinary Result(ok=False, ...), not an unhandled
    crash."""
    try:
        TimeRecord(
            None, date(2026, 6, 26), time(9, 0), time(10, 0), 75, WorkType.REMOTE
        )
        pytest.fail("expected ValueError")
    except ValueError as exc:
        result = Result(ok=False, errors=[str(exc)])

    assert result.ok is False
    assert "Break cannot exceed shift length" in result.errors[0]
