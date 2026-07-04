import calendar
from datetime import date, datetime, time


def now_hm() -> str:
    """Returns the current local time in HH:MM format."""
    return datetime.now().strftime("%H:%M")


def date_to_iso(d: date) -> str:
    """Converts a date object to ISO-8601 string (YYYY-MM-DD)."""
    return d.isoformat()


def iso_to_date(s: str) -> date:
    """Parses an ISO-8601 string (YYYY-MM-DD) into a date object."""
    return date.fromisoformat(s)


def time_to_str(t: time) -> str:
    """Converts a time object to HH:MM format."""
    return t.strftime("%H:%M")


def str_to_time(s: str) -> time:
    """Parses a HH:MM string into a time object."""
    # Supports both HH:MM and HH:MM:SS (if SQLite returns seconds)
    parts = s.split(":")
    if len(parts) >= 2:
        return time(int(parts[0]), int(parts[1]))
    raise ValueError(f"Invalid time format: {s}")


def time_to_minutes(t: time | str) -> int:
    """Converts a time object or HH:MM string to minutes since midnight."""
    if isinstance(t, str):
        t_obj = str_to_time(t)
    else:
        t_obj = t
    return t_obj.hour * 60 + t_obj.minute


def to_display_date(d: date) -> str:
    """Converts a date object to the UI display format dd/mm/yyyy."""
    return d.strftime("%d/%m/%Y")


def period_bounds(year: int, month: int | None = None) -> tuple[str, str]:
    """Returns (start_date, end_date) ISO-8601 strings bounding the given
    year, or a single month of that year if `month` is given.

    The end-of-month bound always comes from `calendar.monthrange`, never a
    hardcoded "-31" (a bug that previously slipped into three near-identical
    copies of this computation across the model layer independently)."""
    if month is not None:
        last_day = calendar.monthrange(year, month)[1]
        return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{last_day:02d}"
    return f"{year:04d}-01-01", f"{year:04d}-12-31"


def duration(start: time | str, end: time | str, break_minutes: int) -> float:
    """
    Calculates the net duration of a shift in hours.
    If end < start, it is treated as an overnight shift.
    """
    start_mins = time_to_minutes(start)
    end_mins = time_to_minutes(end)

    if end_mins >= start_mins:
        total_mins = end_mins - start_mins
    else:
        # Overnight shift
        total_mins = (1440 - start_mins) + end_mins

    net_mins = total_mins - break_minutes
    return net_mins / 60.0
