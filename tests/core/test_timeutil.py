import pytest
from datetime import date, time
from core.timeutil import duration, str_to_time, time_to_str, date_to_iso, iso_to_date

@pytest.mark.parametrize("start,end,brk,expected", [
    ("09:00", "17:00", 30, 7.5),   # normal day
    ("08:30", "12:00", 0,  3.5),   # no break
    ("22:00", "06:00", 0,  8.0),   # overnight wrap
    ("09:00", "09:00", 0,  0.0),   # zero-length
    ("22:00", "06:00", 30, 7.5),  # overnight wrap with break
])
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
