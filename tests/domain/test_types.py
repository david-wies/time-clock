"""Tests for domain/types.py's self-enforced, context-free invariants.

Context-dependent rules (overlap checks, live-settings-derived hour caps)
are NOT tested here — they remain controller-level and are covered by
tests/controllers/*.
"""

from datetime import date, time

import pytest

from domain.enums import VacationType, WorkType
from domain.types import (
    MiliuimRecord,
    PeriodBalance,
    Result,
    SicknessRecord,
    TimeRecord,
    VacationRecord,
)

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


# ─────────────────────────────── PeriodBalance ───────────────────────────────


def test_period_balance_fields() -> None:
    pb = PeriodBalance(
        worked_hours=16.5,
        target_hours=16.0,
        balance=0.5,
        weighted_overtime=0.5,
        days_in_period=2,
    )
    assert pb.worked_hours == 16.5
    assert pb.target_hours == 16.0
    assert pb.balance == 0.5
    assert pb.weighted_overtime == 0.5
    assert pb.days_in_period == 2


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
