"""Unit tests for core/report.py: pure helpers, dataclasses, and period_summary()."""

import pytest
from datetime import date

from core.report import (
    _month_range,
    _period_label,
    _period_range,
    _quarter_months,
    MonthlyRow,
    period_summary,
)
from models.time_clock_model import TimeClockModel
from models.vacation_model import VacationModel
from models.sickness_model import SicknessModel


# ─────────────── Shared fixture ──────────────────────────────────────────────

@pytest.fixture
def period_models(db, event_bus, settings_manager):
    """Returns (tc_model, vac_model, sick_model, settings_manager) sharing one DB."""
    return (
        TimeClockModel(db, event_bus),
        VacationModel(db, event_bus),
        SicknessModel(db, event_bus),
        settings_manager,
    )


# ─────────────── _quarter_months ─────────────────────────────────────────────

@pytest.mark.parametrize("quarter,expected", [
    (1, [1, 2, 3]),
    (2, [4, 5, 6]),
    (3, [7, 8, 9]),
    (4, [10, 11, 12]),
], ids=["Q1", "Q2", "Q3", "Q4"])
def test_quarter_months(quarter, expected):
    assert _quarter_months(quarter) == expected


def test_quarter_months_span_no_gaps():
    # All four quarters together cover every month 1-12 with no overlaps.
    all_months = []
    for q in range(1, 5):
        all_months.extend(_quarter_months(q))
    assert sorted(all_months) == list(range(1, 13))


# ─────────────── _month_range ────────────────────────────────────────────────

@pytest.mark.parametrize("year,month,expected_last", [
    (2026, 1, 31),
    (2025, 2, 28),   # non-leap February
    (2024, 2, 29),   # leap February
    (2026, 6, 30),
    (2026, 9, 30),
    (2026, 12, 31),
], ids=["january", "feb-nonleap", "feb-leap", "june", "september", "december"])
def test_month_range_first_and_last(year, month, expected_last):
    first, last = _month_range(year, month)
    assert first == date(year, month, 1)
    assert last == date(year, month, expected_last)


# ─────────────── _period_range ───────────────────────────────────────────────

def test_period_range_month_june():
    start, end = _period_range("month", 2026, month=6, quarter=None)
    assert start == date(2026, 6, 1)
    assert end == date(2026, 6, 30)


def test_period_range_month_february_nonleap():
    start, end = _period_range("month", 2025, month=2, quarter=None)
    assert start == date(2025, 2, 1)
    assert end == date(2025, 2, 28)


@pytest.mark.parametrize("quarter,exp_start,exp_end", [
    (1, date(2026, 1, 1), date(2026, 3, 31)),
    (2, date(2026, 4, 1), date(2026, 6, 30)),
    (3, date(2026, 7, 1), date(2026, 9, 30)),
    (4, date(2026, 10, 1), date(2026, 12, 31)),
], ids=["Q1", "Q2", "Q3", "Q4"])
def test_period_range_quarter(quarter, exp_start, exp_end):
    start, end = _period_range("quarter", 2026, month=None, quarter=quarter)
    assert start == exp_start
    assert end == exp_end


def test_period_range_year():
    start, end = _period_range("year", 2026, month=None, quarter=None)
    assert start == date(2026, 1, 1)
    assert end == date(2026, 12, 31)


def test_period_range_month_missing_month_raises():
    with pytest.raises(ValueError, match="month is required"):
        _period_range("month", 2026, month=None, quarter=None)


def test_period_range_quarter_missing_quarter_raises():
    with pytest.raises(ValueError, match="quarter is required"):
        _period_range("quarter", 2026, month=None, quarter=None)


def test_period_range_unknown_type_raises():
    with pytest.raises(ValueError, match="Unknown period_type"):
        _period_range("week", 2026, month=None, quarter=None)


# ─────────────── _period_label ───────────────────────────────────────────────

@pytest.mark.parametrize("month,expected_name", [
    (1, "January"),
    (2, "February"),
    (3, "March"),
    (6, "June"),
    (9, "September"),
    (12, "December"),
], ids=["jan", "feb", "mar", "jun", "sep", "dec"])
def test_period_label_month(month, expected_name):
    label = _period_label("month", 2026, month=month, quarter=None)
    assert label == f"{expected_name} 2026"


@pytest.mark.parametrize("quarter", [1, 2, 3, 4])
def test_period_label_quarter(quarter):
    label = _period_label("quarter", 2026, month=None, quarter=quarter)
    assert label == f"Q{quarter} 2026"


def test_period_label_year():
    label = _period_label("year", 2026, month=None, quarter=None)
    assert label == "2026"


def test_period_label_year_reflects_year_arg():
    assert _period_label("year", 2024, None, None) == "2024"
    assert _period_label("year", 2000, None, None) == "2000"


# ─────────────── MonthlyRow dataclass ────────────────────────────────────────

def test_monthly_row_stores_all_fields():
    row = MonthlyRow(month=6, year=2026, worked_hours=7.5,
                     target_hours=8.0, balance=-0.5)
    assert row.month == 6
    assert row.year == 2026
    assert row.worked_hours == pytest.approx(7.5)
    assert row.target_hours == pytest.approx(8.0)
    assert row.balance == pytest.approx(-0.5)


def test_monthly_row_positive_balance():
    row = MonthlyRow(month=1, year=2026, worked_hours=9.0,
                     target_hours=8.0, balance=1.0)
    assert row.balance == pytest.approx(1.0)
    assert row.worked_hours > row.target_hours


# ─────────────── period_summary() — empty database ───────────────────────────

def test_period_summary_month_empty_db_zeroes(period_models):
    tc, vac, sick, sm = period_models
    data = period_summary(
        "month", 2026, month=6, quarter=None,
        model_tc=tc, model_vacation=vac,
        model_sickness=sick, settings=sm,
    )
    assert data.worked_hours == pytest.approx(0.0)
    assert data.target_hours == pytest.approx(0.0)
    assert data.time_balance == pytest.approx(0.0)
    assert data.monthly_rows == []


def test_period_summary_month_stores_metadata(period_models):
    tc, vac, sick, sm = period_models
    data = period_summary(
        "month", 2026, month=3, quarter=None,
        model_tc=tc, model_vacation=vac,
        model_sickness=sick, settings=sm,
    )
    assert data.period_type == "month"
    assert data.year == 2026
    assert data.month == 3
    assert data.quarter is None
    assert data.period_label == "March 2026"
    # "overtime_rate" is in DEFAULTS as 1.0 and not overridden
    assert data.overtime_rate == pytest.approx(1.0)


def test_period_summary_quarter_row_count_and_months(period_models):
    tc, vac, sick, sm = period_models
    data = period_summary(
        "quarter", 2026, month=None, quarter=2,
        model_tc=tc, model_vacation=vac,
        model_sickness=sick, settings=sm,
    )
    assert data.period_type == "quarter"
    assert data.quarter == 2
    assert data.month is None
    assert data.period_label == "Q2 2026"
    assert len(data.monthly_rows) == 3
    assert [row.month for row in data.monthly_rows] == [4, 5, 6]


def test_period_summary_quarter_row_year_field(period_models):
    tc, vac, sick, sm = period_models
    data = period_summary(
        "quarter", 2026, month=None, quarter=1,
        model_tc=tc, model_vacation=vac,
        model_sickness=sick, settings=sm,
    )
    for row in data.monthly_rows:
        assert row.year == 2026


def test_period_summary_quarter_empty_db_rows_zero(period_models):
    tc, vac, sick, sm = period_models
    data = period_summary(
        "quarter", 2026, month=None, quarter=3,
        model_tc=tc, model_vacation=vac,
        model_sickness=sick, settings=sm,
    )
    for row in data.monthly_rows:
        assert row.worked_hours == 0.0
        assert row.target_hours == 0.0


def test_period_summary_year_has_twelve_rows(period_models):
    tc, vac, sick, sm = period_models
    data = period_summary(
        "year", 2026, month=None, quarter=None,
        model_tc=tc, model_vacation=vac,
        model_sickness=sick, settings=sm,
    )
    assert data.period_type == "year"
    assert data.year == 2026
    assert data.month is None
    assert data.quarter is None
    assert len(data.monthly_rows) == 12
    assert [row.month for row in data.monthly_rows] == list(range(1, 13))


def test_period_summary_vac_defaults_with_no_settings(period_models):
    tc, vac, sick, sm = period_models
    data = period_summary(
        "month", 2026, month=6, quarter=None,
        model_tc=tc, model_vacation=vac,
        model_sickness=sick, settings=sm,
    )
    # No vacation settings set → allowance and pool are 0.0
    assert data.vac_allowance == pytest.approx(0.0)
    assert data.vac_used == pytest.approx(0.0)
    assert data.vac_remaining == pytest.approx(0.0)
    # No sickness settings set → default fallback is 10.0 days
    assert data.sick_allowance_days == pytest.approx(10.0)
    assert data.sick_used_hours == pytest.approx(0.0)
