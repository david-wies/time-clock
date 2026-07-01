"""Pure data assembly for Time Clock reports (no PDF rendering, fully unit-testable)."""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from core.balance import calculate_period_balance
from core.timeutil import iso_to_date
from models.miliuim_model import MiliuimModel
from models.time_clock_model import TimeClockModel
from models.vacation_model import VacationModel
from models.sickness_model import SicknessModel
from settings import SettingsManager


MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


@dataclass(slots=True)
class MonthlyRow:
    month: int        # 1-12
    year: int
    worked_hours: float
    target_hours: float
    balance: float    # positive = overtime, negative = deficit


@dataclass(slots=True)
class ReportData:
    period_label: str         # e.g. "June 2026", "Q2 2026", "2026"
    period_type: str          # "month" | "quarter" | "year"
    year: int
    month: Optional[int]      # None for year/quarter reports
    quarter: Optional[int]    # None for month/year reports

    # Time clock
    worked_hours: float
    target_hours: float
    time_balance: float       # worked - target
    weighted_overtime: float  # time_balance * rate if positive
    overtime_rate: float

    # Vacation
    vac_allowance: float
    vac_carry_over: float
    vac_total_pool: float
    vac_used: float
    vac_remaining: float

    # Sickness
    sick_allowance_hours: float
    sick_used_hours: float
    sick_remaining_hours: float

    # Miliuim
    miliuim_period_count: int
    miliuim_total_days: int

    # Monthly breakdown (for quarter/year reports)
    monthly_rows: list[MonthlyRow] = field(default_factory=list)


# ──────────────────────────── Internal helpers ────────────────────────────────

def _quarter_months(quarter: int) -> list[int]:
    """Returns the three month numbers (1-12) for a given quarter (1-4)."""
    start = (quarter - 1) * 3 + 1
    return [start, start + 1, start + 2]


def _month_range(year: int, month: int) -> tuple[date, date]:
    """Returns (first_day, last_day) for the given year/month."""
    first = date(year, month, 1)
    last = date(year, month, calendar.monthrange(year, month)[1])
    return first, last


def _period_range(
    period_type: str,
    year: int,
    month: Optional[int],
    quarter: Optional[int],
) -> tuple[date, date]:
    if period_type == "month":
        if month is None:
            raise ValueError("month is required for period_type='month'")
        return _month_range(year, month)
    if period_type == "quarter":
        if quarter is None:
            raise ValueError("quarter is required for period_type='quarter'")
        months = _quarter_months(quarter)
        return date(year, months[0], 1), _month_range(year, months[-1])[1]
    if period_type == "year":
        return date(year, 1, 1), date(year, 12, 31)
    raise ValueError(f"Unknown period_type: {period_type!r}")


def _period_label(
    period_type: str,
    year: int,
    month: Optional[int],
    quarter: Optional[int],
) -> str:
    if period_type == "month":
        return f"{MONTH_NAMES[month or 1]} {year}"
    if period_type == "quarter":
        return f"Q{quarter} {year}"
    return str(year)


# ──────────────────────────── Public API ─────────────────────────────────────

def period_summary(
    period_type: str,  # "month" | "quarter" | "year"
    year: int,
    # required when period_type="month"; pass None for "quarter" and "year"
    month: Optional[int],
    quarter: Optional[int],  # 1-4, required for "quarter"
    model_tc: TimeClockModel,
    model_vacation: VacationModel,
    model_sickness: SicknessModel,
    settings: SettingsManager,
    model_miliuim: Optional[MiliuimModel] = None,
) -> ReportData:
    """
    Assembles all report data for the requested period.
    No PDF rendering — returns a plain ReportData dataclass.
    """
    overtime_rate = float(settings.get("overtime_rate", 1.0))

    start_date, end_date = _period_range(period_type, year, month, quarter)
    label = _period_label(period_type, year, month, quarter)

    # Fetch records once for the full year so monthly rows can reuse them
    if period_type == "month":
        records = model_tc.get_records_for_period(year, month)
    else:
        records = model_tc.get_records_for_period(year)

    targets = model_tc.get_work_day_targets()

    exceptions: dict[date, float] = {
        iso_to_date(d.date): d.hours
        for d in model_tc.get_date_exceptions(year)
    }

    # Main period balance
    bal = calculate_period_balance(
        records, start_date, end_date, targets, exceptions, overtime_rate
    )

    # Monthly breakdown rows (only for quarter / year periods)
    monthly_rows: list[MonthlyRow] = []
    if period_type in ("quarter", "year"):
        months_in_period: list[int] = (
            _quarter_months(quarter)  # type: ignore[arg-type]
            if period_type == "quarter"
            else list(range(1, 13))
        )
        for m in months_in_period:
            m_start, m_end = _month_range(year, m)
            m_bal = calculate_period_balance(
                records, m_start, m_end, targets, exceptions, overtime_rate
            )
            monthly_rows.append(MonthlyRow(
                month=m,
                year=year,
                worked_hours=m_bal["worked_hours"],
                target_hours=m_bal["target_hours"],
                balance=m_bal["balance"],
            ))

    # Vacation and sickness summaries are always year-level
    vac = model_vacation.calculate_vacation_summary(year)
    sick = model_sickness.calculate_sickness_summary(year)
    miliuim = model_miliuim.calculate_summary(
        year) if model_miliuim is not None else None

    return ReportData(
        period_label=label,
        period_type=period_type,
        year=year,
        month=month,
        quarter=quarter,
        worked_hours=bal["worked_hours"],
        target_hours=bal["target_hours"],
        time_balance=bal["balance"],
        weighted_overtime=bal["weighted_overtime"],
        overtime_rate=overtime_rate,
        vac_allowance=vac.allowance,
        vac_carry_over=vac.carry_over,
        vac_total_pool=vac.total_pool,
        vac_used=vac.used,
        vac_remaining=vac.remaining,
        sick_allowance_hours=sick.allowance_hours,
        sick_used_hours=sick.used_hours,
        sick_remaining_hours=sick.remaining_hours,
        miliuim_period_count=miliuim.period_count if miliuim is not None else 0,
        miliuim_total_days=miliuim.total_days if miliuim is not None else 0,
        monthly_rows=monthly_rows,
    )
