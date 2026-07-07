"""Worked-hours/target-hours balance calculations over date ranges."""

from datetime import date, datetime, time, timedelta

from core.timeutil import duration
from domain.types import PeriodBalance, TimeRecord


def get_daily_target(
    target_date: date, targets: dict[int, float], exceptions: dict[date, float]
) -> float:
    """Returns the target hours for a specific date, checking exceptions first."""
    if target_date in exceptions:
        return exceptions[target_date]
    return targets.get(target_date.weekday(), 0.0)


def get_record_duration(rec: TimeRecord, today: date, now_time: time) -> float:
    """Calculates duration of a record. If open and is today, computes elapsed time."""
    if rec.end_time is not None:
        return duration(rec.start_time, rec.end_time, rec.break_minutes)

    # Open record
    if rec.date == today:
        # Compute elapsed time from start to now
        return duration(rec.start_time, now_time, rec.break_minutes)

    # Open record on a past day (or future): treat as 0.0 until closed
    return 0.0


def sum_day_worked(day_records: list[TimeRecord], today: date, now_time: time) -> float:
    """Sums worked hours for a single day's records, guarding against
    double-counting when multiple simultaneously-open records exist for
    `today` (e.g. a force-clock-in over an already-open record). Physically,
    only one "still clocked in" span can be accruing elapsed time at once, so
    among today-dated open records (end_time=None) only the one with the
    earliest start_time contributes; all closed records still each
    contribute their own duration independently, as before.
    """
    open_today_records = [
        rec for rec in day_records if rec.end_time is None and rec.date == today
    ]
    other_records = [rec for rec in day_records if rec not in open_today_records]

    total = sum(get_record_duration(rec, today, now_time) for rec in other_records)

    if open_today_records:
        earliest_open = min(open_today_records, key=lambda rec: rec.start_time)
        total += get_record_duration(earliest_open, today, now_time)

    return total


def group_records_by_date(records: list[TimeRecord]) -> dict[date, list[TimeRecord]]:
    """Groups records by their `date` field. O(N) — call once and reuse the
    result across multiple `period_balance_from_grouped()` calls (e.g. an
    overall-period balance plus a per-month breakdown over the same
    records) instead of re-scanning the full list for every sub-range."""
    records_by_date: dict[date, list[TimeRecord]] = {}
    for rec in records:
        records_by_date.setdefault(rec.date, []).append(rec)
    return records_by_date


def period_balance_from_grouped(
    records_by_date: dict[date, list[TimeRecord]],
    start_date: date,
    end_date: date,
    targets: dict[int, float],
    exceptions: dict[date, float],
    overtime_rate: float = 1.0,
    today: date | None = None,
    now_time: time | None = None,
) -> PeriodBalance:
    """
    Computes total worked hours, target hours, and balances for a date range,
    given records already grouped by date (see `group_records_by_date`).
    Overtime rate multiplier is applied only to positive balances.

    This is the O(days_in_range) core of `calculate_period_balance` --
    factored out so callers that need the balance for several sub-ranges of
    the same underlying record set (e.g. core/report.py's monthly
    breakdown) can group once and slice many times, instead of re-grouping
    the full record list on every call.
    """
    if today is None:
        today = date.today()
    if now_time is None:
        now_time = datetime.now().time()

    total_worked = 0.0
    total_target = 0.0

    # Iterate through every day in the range
    delta = end_date - start_date
    num_days = delta.days + 1

    for i in range(num_days):
        current_date = start_date + timedelta(days=i)

        # Add target
        target = get_daily_target(current_date, targets, exceptions)
        total_target += target

        # Add worked
        day_records = records_by_date.get(current_date, [])
        total_worked += sum_day_worked(day_records, today, now_time)

    balance = total_worked - total_target

    # Overtime rate only applies to positive balances (surplus)
    if balance > 0:
        weighted_overtime = balance * overtime_rate
    else:
        weighted_overtime = balance

    return PeriodBalance(
        worked_hours=total_worked,
        target_hours=total_target,
        balance=balance,
        weighted_overtime=weighted_overtime,
        days_in_period=num_days,
    )


def calculate_period_balance(
    records: list[TimeRecord],
    start_date: date,
    end_date: date,
    targets: dict[int, float],
    exceptions: dict[date, float],
    overtime_rate: float = 1.0,
    today: date | None = None,
    now_time: time | None = None,
) -> PeriodBalance:
    """
    Computes total worked hours, target hours, and balances for a date range.
    Overtime rate multiplier is applied only to positive balances.
    """
    records_by_date = group_records_by_date(records)
    return period_balance_from_grouped(
        records_by_date,
        start_date,
        end_date,
        targets,
        exceptions,
        overtime_rate=overtime_rate,
        today=today,
        now_time=now_time,
    )


def get_week_range(target_date: date) -> tuple[date, date]:
    """Returns the (Monday, Sunday) date range of the week containing target_date."""
    # weekday() returns 0 for Mon, 6 for Sun
    start = target_date - timedelta(days=target_date.weekday())
    end = start + timedelta(days=6)
    return start, end


def get_month_range(target_date: date) -> tuple[date, date]:
    """Returns the (1st, last day) date range of the month containing target_date."""
    start = date(target_date.year, target_date.month, 1)
    # Finding last day of the month
    if target_date.month == 12:
        end = date(target_date.year, 12, 31)
    else:
        # First day of next month minus 1 day
        next_month = date(target_date.year, target_date.month + 1, 1)
        end = next_month - timedelta(days=1)
    return start, end


def get_year_range(target_date: date) -> tuple[date, date]:
    """Returns the (Jan 1, Dec 31) date range of the year containing target_date."""
    return date(target_date.year, 1, 1), date(target_date.year, 12, 31)


# Alias matching §18.3 spec name
period_balance = calculate_period_balance


def overtime(
    records: list[TimeRecord],
    start_date: date,
    end_date: date,
    targets: dict[int, float],
    exceptions: dict[date, float],
    rate: float = 1.0,
    today: date | None = None,
    now_time: time | None = None,
) -> tuple[float, float]:
    """
    Returns (raw_hours, weighted_hours) for the period (§21.3).
    Rate applies only to positive balances (surplus); deficit is returned raw.
    """
    result = calculate_period_balance(
        records,
        start_date,
        end_date,
        targets,
        exceptions,
        overtime_rate=rate,
        today=today,
        now_time=now_time,
    )
    raw = result.balance
    weighted = result.weighted_overtime
    return raw, weighted
