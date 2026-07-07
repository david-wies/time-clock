from datetime import date, time

import pytest

from core.balance import (
    calculate_period_balance,
    get_daily_target,
    get_month_range,
    get_week_range,
    get_year_range,
    group_records_by_date,
    period_balance_from_grouped,
)
from domain.enums import WorkType
from domain.types import TimeRecord


def test_get_daily_target() -> None:
    targets = {
        0: 8.0,  # Mon
        1: 8.0,  # Tue
        4: 6.0,  # Fri
        5: 0.0,  # Sat
    }
    exceptions = {
        date(2026, 6, 26): 4.0,  # Specific override (a Friday)
    }

    # Exception check: Friday, June 26, 2026
    assert get_daily_target(date(2026, 6, 26), targets, exceptions) == 4.0

    # Normal Friday (no exception): June 19, 2026
    assert get_daily_target(date(2026, 6, 19), targets, exceptions) == 6.0

    # Normal Monday (no exception): June 22, 2026
    assert get_daily_target(date(2026, 6, 22), targets, exceptions) == 8.0

    # Day without target in dict defaults to 0.0: Sunday (6)
    assert get_daily_target(date(2026, 6, 28), targets, exceptions) == 0.0


def test_calculate_period_balance() -> None:
    targets = {0: 8.0, 1: 8.0, 2: 8.0, 3: 8.0, 4: 8.0, 5: 0.0, 6: 0.0}
    exceptions = {}

    # Create time records
    records = [
        TimeRecord(
            1, date(2026, 6, 22), time(9, 0), time(17, 0), 30, WorkType.REMOTE
        ),  # Worked 7.5h (target 8.0)
        TimeRecord(
            2, date(2026, 6, 23), time(9, 0), time(18, 0), 0, WorkType.REMOTE
        ),  # Worked 9.0h (target 8.0)
    ]

    # Calculate balance for Mon-Tue (2 days, total target = 16.0h)
    result = calculate_period_balance(
        records,
        start_date=date(2026, 6, 22),
        end_date=date(2026, 6, 23),
        targets=targets,
        exceptions=exceptions,
        today=date(2026, 6, 26),
    )

    # Worked: 7.5 + 9.0 = 16.5h
    assert result.worked_hours == 16.5
    assert result.target_hours == 16.0
    assert result.balance == 0.5
    assert result.weighted_overtime == 0.5  # default rate 1.0


def test_calculate_period_balance_overtime_rate() -> None:
    targets = {0: 8.0, 1: 8.0, 2: 8.0, 3: 8.0, 4: 8.0, 5: 0.0, 6: 0.0}
    exceptions = {}

    # Positive balance (surplus)
    records_surplus = [
        TimeRecord(
            1, date(2026, 6, 22), time(8, 0), time(18, 0), 0, WorkType.REMOTE
        ),  # Worked 10h (target 8h)
    ]
    res_surplus = calculate_period_balance(
        records_surplus,
        start_date=date(2026, 6, 22),
        end_date=date(2026, 6, 22),
        targets=targets,
        exceptions=exceptions,
        overtime_rate=1.5,
        today=date(2026, 6, 26),
    )
    assert res_surplus.balance == 2.0
    assert res_surplus.weighted_overtime == 3.0  # 2.0 * 1.5

    # Negative balance (deficit)
    records_deficit = [
        TimeRecord(
            1, date(2026, 6, 22), time(9, 0), time(15, 0), 0, WorkType.REMOTE
        ),  # Worked 6h (target 8h)
    ]
    res_deficit = calculate_period_balance(
        records_deficit,
        start_date=date(2026, 6, 22),
        end_date=date(2026, 6, 22),
        targets=targets,
        exceptions=exceptions,
        overtime_rate=1.5,
        today=date(2026, 6, 26),
    )
    assert res_deficit.balance == -2.0
    assert res_deficit.weighted_overtime == -2.0  # Deficit is raw, rate not applied


# ─────────────── group_records_by_date / period_balance_from_grouped ───────
# These back calculate_period_balance's O(N)-per-call contract: group once,
# reuse the same records_by_date dict across many sub-range slices (used by
# core/report.py's monthly-breakdown loop, avoiding an O(13N) rescan).


def test_group_records_by_date_groups_by_date_key() -> None:
    records = [
        TimeRecord(1, date(2026, 6, 22), time(9, 0), time(17, 0), 0, WorkType.REMOTE),
        TimeRecord(2, date(2026, 6, 22), time(18, 0), time(19, 0), 0, WorkType.REMOTE),
        TimeRecord(3, date(2026, 6, 23), time(9, 0), time(17, 0), 0, WorkType.REMOTE),
    ]
    grouped = group_records_by_date(records)
    assert set(grouped.keys()) == {date(2026, 6, 22), date(2026, 6, 23)}
    assert [r.id for r in grouped[date(2026, 6, 22)]] == [1, 2]
    assert [r.id for r in grouped[date(2026, 6, 23)]] == [3]


def test_group_records_by_date_empty_list() -> None:
    assert group_records_by_date([]) == {}


def test_period_balance_from_grouped_matches_calculate_period_balance() -> None:
    """The grouped-input helper must produce bit-for-bit identical results
    to calculate_period_balance() for the same records/range — it's the
    same computation, just fed a pre-built records_by_date instead of a
    raw list."""
    targets = {0: 8.0, 1: 8.0, 2: 8.0, 3: 8.0, 4: 8.0, 5: 0.0, 6: 0.0}
    exceptions: dict = {}
    records = [
        TimeRecord(1, date(2026, 6, 22), time(9, 0), time(17, 0), 30, WorkType.REMOTE),
        TimeRecord(2, date(2026, 6, 23), time(9, 0), time(18, 0), 0, WorkType.REMOTE),
    ]

    expected = calculate_period_balance(
        records,
        start_date=date(2026, 6, 22),
        end_date=date(2026, 6, 23),
        targets=targets,
        exceptions=exceptions,
        overtime_rate=1.5,
        today=date(2026, 6, 26),
    )

    grouped = group_records_by_date(records)
    actual = period_balance_from_grouped(
        grouped,
        start_date=date(2026, 6, 22),
        end_date=date(2026, 6, 23),
        targets=targets,
        exceptions=exceptions,
        overtime_rate=1.5,
        today=date(2026, 6, 26),
    )

    assert actual == expected


def test_period_balance_from_grouped_reused_dict_across_sub_ranges() -> None:
    """A single records_by_date built from a full year's records must give
    correct, independent results when reused for multiple, non-overlapping
    sub-range slices (the core/report.py monthly-breakdown use case)."""
    targets = {0: 8.0, 1: 8.0, 2: 8.0, 3: 8.0, 4: 8.0, 5: 0.0, 6: 0.0}
    exceptions: dict = {}
    records = [
        TimeRecord(1, date(2026, 1, 5), time(9, 0), time(17, 0), 0, WorkType.REMOTE),
        TimeRecord(2, date(2026, 2, 10), time(9, 0), time(17, 0), 0, WorkType.REMOTE),
    ]
    grouped = group_records_by_date(records)

    jan = period_balance_from_grouped(
        grouped,
        date(2026, 1, 1),
        date(2026, 1, 31),
        targets,
        exceptions,
        today=date(2026, 12, 31),
    )
    feb = period_balance_from_grouped(
        grouped,
        date(2026, 2, 1),
        date(2026, 2, 28),
        targets,
        exceptions,
        today=date(2026, 12, 31),
    )
    mar = period_balance_from_grouped(
        grouped,
        date(2026, 3, 1),
        date(2026, 3, 31),
        targets,
        exceptions,
        today=date(2026, 12, 31),
    )

    assert jan.worked_hours == 8.0
    assert feb.worked_hours == 8.0
    assert mar.worked_hours == 0.0


# ─────────────── get_record_duration via calculate_period_balance ──────────
# get_record_duration() (private to core/balance.py) has three branches:
# (a) closed record — plain duration(); (b) open record dated `today` —
# elapsed time from start_time to now_time; (c) open record on a past/future
# day — contributes 0.0 until closed. Exercised here through the public
# calculate_period_balance() API, passing today/now_time explicitly.


def test_calculate_period_balance_closed_record_uses_start_end_duration() -> None:
    targets = {0: 8.0, 1: 8.0, 2: 8.0, 3: 8.0, 4: 8.0, 5: 0.0, 6: 0.0}
    records = [
        TimeRecord(1, date(2026, 6, 22), time(9, 0), time(17, 0), 30, WorkType.REMOTE),
    ]

    result = calculate_period_balance(
        records,
        start_date=date(2026, 6, 22),
        end_date=date(2026, 6, 22),
        targets=targets,
        exceptions={},
        today=date(2026, 6, 26),
        now_time=time(23, 0),
    )

    # 9:00-17:00 minus 30min break = 7.5h, regardless of today/now_time.
    assert result.worked_hours == 7.5
    assert result.balance == -0.5


def test_calculate_period_balance_open_record_today_uses_elapsed_time() -> None:
    """An open record (end_time=None) dated `today` must contribute elapsed
    time computed from start_time to the supplied now_time, not 0.0."""
    targets = {0: 8.0, 1: 8.0, 2: 8.0, 3: 8.0, 4: 8.0, 5: 0.0, 6: 0.0}
    records = [
        TimeRecord(1, date(2026, 6, 22), time(9, 0), None, 0, WorkType.REMOTE),
    ]

    result = calculate_period_balance(
        records,
        start_date=date(2026, 6, 22),
        end_date=date(2026, 6, 22),
        targets=targets,
        exceptions={},
        today=date(2026, 6, 22),
        now_time=time(13, 30),
    )

    # Elapsed from 9:00 to 13:30 = 4.5h.
    assert result.worked_hours == 4.5
    assert result.balance == pytest.approx(4.5 - 8.0)


def test_calculate_period_balance_open_record_on_past_day_contributes_zero() -> None:
    """An open record dated a day other than `today` (still clocked in from
    a prior day, or a data artifact) must contribute 0.0, not attempt an
    elapsed-time computation against an unrelated `today`."""
    targets = {0: 8.0, 1: 8.0, 2: 8.0, 3: 8.0, 4: 8.0, 5: 0.0, 6: 0.0}
    records = [
        TimeRecord(1, date(2026, 6, 22), time(9, 0), None, 0, WorkType.REMOTE),
    ]

    result = calculate_period_balance(
        records,
        start_date=date(2026, 6, 22),
        end_date=date(2026, 6, 22),
        targets=targets,
        exceptions={},
        today=date(2026, 6, 23),  # "today" has moved on; record is stale-open
        now_time=time(13, 30),
    )

    assert result.worked_hours == 0.0
    assert result.balance == -8.0


def test_calculate_period_balance_open_record_on_future_day_contributes_zero() -> None:
    """Symmetric case: an open record dated after `today` (shouldn't happen
    in practice, but get_record_duration's `rec.date == today` branch is a
    strict equality check either direction) also contributes 0.0."""
    targets = {0: 8.0, 1: 8.0, 2: 8.0, 3: 8.0, 4: 8.0, 5: 0.0, 6: 0.0}
    records = [
        TimeRecord(1, date(2026, 6, 23), time(9, 0), None, 0, WorkType.REMOTE),
    ]

    result = calculate_period_balance(
        records,
        start_date=date(2026, 6, 23),
        end_date=date(2026, 6, 23),
        targets=targets,
        exceptions={},
        today=date(2026, 6, 22),
        now_time=time(13, 30),
    )

    assert result.worked_hours == 0.0


def test_period_balance_from_grouped_two_open_records_same_day_no_double_count() -> (
    None
):
    """Regression: a force-clock-in can leave two simultaneously-open
    TimeRecords (end_time=None) for the same date. Physically, only one
    "still clocked in" span can be accruing elapsed time at once, so the
    balance must count elapsed time from the earliest-starting open record
    only -- not the sum of both, which would double-count wall-clock time."""
    targets = {0: 8.0, 1: 8.0, 2: 8.0, 3: 8.0, 4: 8.0, 5: 0.0, 6: 0.0}
    records = [
        TimeRecord(1, date(2026, 6, 22), time(9, 0), None, 0, WorkType.REMOTE),
        TimeRecord(2, date(2026, 6, 22), time(13, 0), None, 0, WorkType.REMOTE),
    ]

    grouped = group_records_by_date(records)
    result = period_balance_from_grouped(
        grouped,
        start_date=date(2026, 6, 22),
        end_date=date(2026, 6, 22),
        targets=targets,
        exceptions={},
        today=date(2026, 6, 22),
        now_time=time(15, 0),
    )

    # Expected: elapsed time from the earliest start (9:00) to now (15:00) =
    # 6.0h. NOT 6.0 + 2.0 = 8.0h (the buggy double-count of both open spans).
    assert result.worked_hours == 6.0
    assert result.balance == pytest.approx(6.0 - 8.0)


def test_get_week_range_crosses_year_boundary() -> None:
    """The week containing Jan 1, 2027 (a Friday) starts Mon Dec 28, 2026
    and ends Sun Jan 3, 2027 — get_week_range must cross the Dec 31 -> Jan 1
    boundary without an off-by-one on either the year or the day count."""
    w_start, w_end = get_week_range(date(2027, 1, 1))
    assert w_start == date(2026, 12, 28)
    assert w_end == date(2027, 1, 3)
    assert (w_end - w_start).days == 6


def test_date_range_helpers() -> None:
    # Friday, June 26, 2026
    d = date(2026, 6, 26)

    # Week range (Mon-Sun)
    w_start, w_end = get_week_range(d)
    assert w_start == date(2026, 6, 22)  # Monday
    assert w_end == date(2026, 6, 28)  # Sunday

    # Month range (1st to last)
    m_start, m_end = get_month_range(d)
    assert m_start == date(2026, 6, 1)
    assert m_end == date(2026, 6, 30)

    # Dec month range check
    dec_start, dec_end = get_month_range(date(2026, 12, 15))
    assert dec_start == date(2026, 12, 1)
    assert dec_end == date(2026, 12, 31)

    # Year range
    y_start, y_end = get_year_range(d)
    assert y_start == date(2026, 1, 1)
    assert y_end == date(2026, 12, 31)
