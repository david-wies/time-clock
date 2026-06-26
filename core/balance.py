from datetime import date, time, datetime, timedelta
from typing import Optional, Any, Union
from domain.types import TimeRecord
from core.timeutil import duration

def get_daily_target(target_date: date, targets: dict[int, float], exceptions: dict[date, float]) -> float:
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

def calculate_period_balance(
    records: list[TimeRecord],
    start_date: date,
    end_date: date,
    targets: dict[int, float],
    exceptions: dict[date, float],
    overtime_rate: float = 1.0,
    today: Optional[date] = None,
    now_time: Optional[time] = None
) -> dict[str, Any]:
    """
    Computes total worked hours, target hours, and balances for a date range.
    Overtime rate multiplier is applied only to positive balances.
    """
    if today is None:
        today = date.today()
    if now_time is None:
        now_time = datetime.now().time()

    # Group records by date for easy access
    records_by_date: dict[date, list[TimeRecord]] = {}
    for rec in records:
        if start_date <= rec.date <= end_date:
            records_by_date.setdefault(rec.date, []).append(rec)

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
        for rec in day_records:
            total_worked += get_record_duration(rec, today, now_time)

    balance = total_worked - total_target
    
    # Overtime rate only applies to positive balances (surplus)
    if balance > 0:
        weighted_overtime = balance * overtime_rate
    else:
        weighted_overtime = balance

    return {
        "worked_hours": total_worked,
        "target_hours": total_target,
        "balance": balance,
        "weighted_overtime": weighted_overtime,
        "days_in_period": num_days
    }

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
