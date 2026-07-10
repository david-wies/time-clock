from datetime import date, time

import pytest

from core.timeutil import (
    date_to_iso,
    duration,
    iso_to_date,
    now_hm,
    period_bounds,
    str_to_time,
    time_to_str,
    to_display_date,
)


@pytest.mark.parametrize(
    "start,end,brk,expected",
    [
        ("09:00", "17:00", 30, 7.5),  # normal day
        ("08:30", "12:00", 0, 3.5),  # no break
        ("22:00", "06:00", 0, 8.0),  # overnight wrap
        ("09:00", "09:00", 0, 0.0),  # zero-length
        ("22:00", "06:00", 30, 7.5),  # overnight wrap with break
    ],
)
def test_duration(start, end, brk, expected) -> None:
    assert duration(start, end, brk) == pytest.approx(expected)


def test_break_exceeds_shift_is_negative() -> None:
    # 09:00 to 10:00 is 1 hour (60 min). Break is 90 mins (1.5h). Net is -0.5h.
    assert duration("09:00", "10:00", 90) < 0


def test_time_conversions() -> None:
    assert time_to_str(time(9, 30)) == "09:30"
    assert str_to_time("09:30") == time(9, 30)
    assert str_to_time("14:45:00") == time(14, 45)  # supports seconds fallback

    with pytest.raises(ValueError):
        str_to_time("invalid-time")


def test_date_conversions() -> None:
    d = date(2026, 6, 26)
    assert date_to_iso(d) == "2026-06-26"
    assert iso_to_date("2026-06-26") == d


def test_to_display_date() -> None:
    assert to_display_date(date(2026, 6, 26)) == "26/06/2026"
    assert to_display_date(date(2026, 1, 1)) == "01/01/2026"


def test_now_hm_format() -> None:
    result = now_hm()
    parts = result.split(":")
    assert len(parts) == 2
    assert parts[0].isdigit() and parts[1].isdigit()
    assert 0 <= int(parts[0]) <= 23
    assert 0 <= int(parts[1]) <= 59


@pytest.mark.parametrize(
    "year, month, expected_last_day",
    [
        (2024, 2, 29),  # leap-year February
        (2026, 2, 28),  # non-leap-year February
        (2026, 4, 30),  # 30-day month
        (2026, 12, 31),  # year-end month
    ],
)
def test_period_bounds_with_month_uses_real_month_end_date(
    year: int, month: int, expected_last_day: int
) -> None:
    start, end = period_bounds(year, month)
    assert start == f"{year:04d}-{month:02d}-01"
    assert end == f"{year:04d}-{month:02d}-{expected_last_day:02d}"


def test_period_bounds_without_month_spans_full_year() -> None:
    start, end = period_bounds(2026)
    assert start == "2026-01-01"
    assert end == "2026-12-31"
