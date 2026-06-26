import pytest
from datetime import date, time
from domain.types import TimeRecord
from domain.enums import WorkType
from core.balance import (
    get_daily_target,
    calculate_period_balance,
    get_week_range,
    get_month_range,
    get_year_range
)


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
        TimeRecord(1, date(2026, 6, 22), time(9, 0), time(17, 0),
                   30, WorkType.REMOTE),  # Worked 7.5h (target 8.0)
        TimeRecord(2, date(2026, 6, 23), time(9, 0), time(18, 0),
                   0, WorkType.REMOTE),   # Worked 9.0h (target 8.0)
    ]

    # Calculate balance for Mon-Tue (2 days, total target = 16.0h)
    result = calculate_period_balance(
        records,
        start_date=date(2026, 6, 22),
        end_date=date(2026, 6, 23),
        targets=targets,
        exceptions=exceptions,
        today=date(2026, 6, 26)
    )

    # Worked: 7.5 + 9.0 = 16.5h
    assert result["worked_hours"] == 16.5
    assert result["target_hours"] == 16.0
    assert result["balance"] == 0.5
    assert result["weighted_overtime"] == 0.5  # default rate 1.0


def test_calculate_period_balance_overtime_rate() -> None:
    targets = {0: 8.0, 1: 8.0, 2: 8.0, 3: 8.0, 4: 8.0, 5: 0.0, 6: 0.0}
    exceptions = {}

    # Positive balance (surplus)
    records_surplus = [
        TimeRecord(1, date(2026, 6, 22), time(8, 0), time(18, 0),
                   0, WorkType.REMOTE),  # Worked 10h (target 8h)
    ]
    res_surplus = calculate_period_balance(
        records_surplus,
        start_date=date(2026, 6, 22),
        end_date=date(2026, 6, 22),
        targets=targets,
        exceptions=exceptions,
        overtime_rate=1.5,
        today=date(2026, 6, 26)
    )
    assert res_surplus["balance"] == 2.0
    assert res_surplus["weighted_overtime"] == 3.0  # 2.0 * 1.5

    # Negative balance (deficit)
    records_deficit = [
        TimeRecord(1, date(2026, 6, 22), time(9, 0), time(15, 0),
                   0, WorkType.REMOTE),  # Worked 6h (target 8h)
    ]
    res_deficit = calculate_period_balance(
        records_deficit,
        start_date=date(2026, 6, 22),
        end_date=date(2026, 6, 22),
        targets=targets,
        exceptions=exceptions,
        overtime_rate=1.5,
        today=date(2026, 6, 26)
    )
    assert res_deficit["balance"] == -2.0
    assert res_deficit["weighted_overtime"] == - \
        2.0  # Deficit is raw, rate not applied


def test_date_range_helpers() -> None:
    # Friday, June 26, 2026
    d = date(2026, 6, 26)

    # Week range (Mon-Sun)
    w_start, w_end = get_week_range(d)
    assert w_start == date(2026, 6, 22)  # Monday
    assert w_end == date(2026, 6, 28)    # Sunday

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
