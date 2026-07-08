"""Pure data assembly for Time Clock reports (no PDF rendering, fully unit-testable)."""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date

from core.balance import group_records_by_date, period_balance_from_grouped
from core.timeutil import MONTH_NAMES
from domain.enums import PeriodType
from models.miliuim_model import MiliuimModel
from models.sickness_model import SicknessModel
from models.time_clock_model import TimeClockModel
from models.vacation_model import VacationModel
from settings import SettingsManager


@dataclass(slots=True)
class MonthlyRow:
    """One month's worked/target/balance figures within a quarter or year report."""

    month: int  # 1-12
    year: int
    worked_hours: float
    target_hours: float
    balance: float  # positive = overtime, negative = deficit


@dataclass(slots=True)
class ReportData:
    """Full assembled report figures (time/vacation/sickness/miliuim) for a period."""

    period_label: str  # e.g. "June 2026", "Q2 2026", "2026"
    period_type: PeriodType
    year: int
    month: int | None  # None for year/quarter reports
    quarter: int | None  # None for month/year reports

    # Time clock
    worked_hours: float
    target_hours: float
    time_balance: float  # worked - target
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

    # Count of malformed DB rows silently dropped (across time clock,
    # vacation, sickness, and miliuim models) while assembling this report.
    # See models/_row_mapping.py:rows_to_records() and
    # views/record_tab_common.py:RecordTabMixin._append_skip_notice() for
    # the underlying mechanism. period_summary() sums each model's
    # last_skipped_count into this field so callers (report_dialog.py,
    # export_dialog.py) can surface a data-integrity warning to the user --
    # unlike the record tabs, this dataclass has no label of its own to
    # append the notice to.
    skipped_record_count: int = 0


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


def period_range(
    period_type: PeriodType,
    year: int,
    month: int | None,
    quarter: int | None,
) -> tuple[date, date]:
    """Returns (start_date, end_date) for the given period_type/year/month/quarter."""
    if period_type == PeriodType.MONTH:
        if month is None:
            raise ValueError("month is required for period_type='month'")
        return _month_range(year, month)
    if period_type == PeriodType.QUARTER:
        if quarter is None:
            raise ValueError("quarter is required for period_type='quarter'")
        months = _quarter_months(quarter)
        return date(year, months[0], 1), _month_range(year, months[-1])[1]
    if period_type == PeriodType.YEAR:
        return date(year, 1, 1), date(year, 12, 31)
    raise ValueError(f"Unknown period_type: {period_type!r}")


_period_range = period_range


def _period_label(
    period_type: PeriodType,
    year: int,
    month: int | None,
    quarter: int | None,
) -> str:
    if period_type == PeriodType.MONTH:
        return f"{MONTH_NAMES[month or 1]} {year}"
    if period_type == PeriodType.QUARTER:
        return f"Q{quarter} {year}"
    return str(year)


# ──────────────────────────── Public API ─────────────────────────────────────


def period_summary(
    period_type: PeriodType,
    year: int,
    # required when period_type="month"; pass None for "quarter" and "year"
    month: int | None,
    quarter: int | None,  # 1-4, required for "quarter"
    model_tc: TimeClockModel,
    model_vacation: VacationModel,
    model_sickness: SicknessModel,
    settings: SettingsManager,
    model_miliuim: MiliuimModel | None = None,
) -> ReportData:
    """
    Assembles all report data for the requested period.
    No PDF rendering — returns a plain ReportData dataclass.
    """
    overtime_rate = float(settings.get("overtime_rate", 1.0))

    start_date, end_date = period_range(period_type, year, month, quarter)
    label = _period_label(period_type, year, month, quarter)

    # Fetch records once for the full year so monthly rows can reuse them
    if period_type == PeriodType.MONTH:
        records = model_tc.get_records_for_period(year, month)
    else:
        records = model_tc.get_records_for_period(year)
    # get_records_for_period() is the last list-fetch call on model_tc
    # before this point, so last_skipped_count reflects it here -- captured
    # before get_work_day_targets()/get_date_exceptions() run (neither of
    # which goes through _rows_to_records(), so neither overwrites it, but
    # capturing immediately keeps this correct even if that changes).
    skipped_record_count = model_tc.last_skipped_count

    targets = model_tc.get_work_day_targets()

    exceptions: dict[date, float] = {
        d.date: d.hours for d in model_tc.get_date_exceptions(year)
    }

    # Group once (O(N)) and reuse for both the overall balance and every
    # monthly slice below, instead of re-scanning `records` from scratch on
    # each of up to 13 calculate_period_balance() calls (O(13N)).
    records_by_date = group_records_by_date(records)

    # Main period balance
    bal = period_balance_from_grouped(
        records_by_date, start_date, end_date, targets, exceptions, overtime_rate
    )

    # Monthly breakdown rows (only for quarter / year periods)
    monthly_rows: list[MonthlyRow] = []
    if period_type in {PeriodType.QUARTER, PeriodType.YEAR}:
        if period_type == PeriodType.QUARTER:
            if quarter is None:
                raise ValueError("quarter is required for period_type='quarter'")
            months_in_period: list[int] = _quarter_months(quarter)
        else:
            months_in_period = list(range(1, 13))
        for m in months_in_period:
            m_start, m_end = _month_range(year, m)
            m_bal = period_balance_from_grouped(
                records_by_date, m_start, m_end, targets, exceptions, overtime_rate
            )
            monthly_rows.append(
                MonthlyRow(
                    month=m,
                    year=year,
                    worked_hours=m_bal.worked_hours,
                    target_hours=m_bal.target_hours,
                    balance=m_bal.balance,
                )
            )

    # Vacation and sickness summaries are always year-level. Each call below
    # fetches its own year's records internally (no `records=` override is
    # passed here) and so sets that model's last_skipped_count -- captured
    # immediately after each call, before the next call overwrites it.
    vac = model_vacation.calculate_vacation_summary(year)
    skipped_record_count += model_vacation.last_skipped_count
    sick = model_sickness.calculate_sickness_summary(year)
    skipped_record_count += model_sickness.last_skipped_count
    miliuim = (
        model_miliuim.calculate_summary(year) if model_miliuim is not None else None
    )
    if model_miliuim is not None:
        skipped_record_count += model_miliuim.last_skipped_count

    return ReportData(
        period_label=label,
        period_type=period_type,
        year=year,
        month=month,
        quarter=quarter,
        worked_hours=bal.worked_hours,
        target_hours=bal.target_hours,
        time_balance=bal.balance,
        weighted_overtime=bal.weighted_overtime,
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
        skipped_record_count=skipped_record_count,
    )
