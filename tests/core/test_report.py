"""Unit tests for core/report.py: pure helpers, dataclasses, and period_summary()."""

from datetime import date, time

import pytest

import core.report as report_module
from core.balance import calculate_period_balance
from core.report import (
    MonthlyRow,
    _month_range,
    _period_label,
    _period_range,
    _quarter_months,
    period_summary,
)
from domain.enums import WorkType
from domain.types import TimeRecord
from models.sickness_model import SicknessModel
from models.time_clock_model import TimeClockModel
from models.vacation_model import VacationModel

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


@pytest.mark.parametrize(
    "quarter,expected",
    [
        (1, [1, 2, 3]),
        (2, [4, 5, 6]),
        (3, [7, 8, 9]),
        (4, [10, 11, 12]),
    ],
    ids=["Q1", "Q2", "Q3", "Q4"],
)
def test_quarter_months(quarter, expected):
    assert _quarter_months(quarter) == expected


def test_quarter_months_span_no_gaps():
    # All four quarters together cover every month 1-12 with no overlaps.
    all_months = []
    for q in range(1, 5):
        all_months.extend(_quarter_months(q))
    assert sorted(all_months) == list(range(1, 13))


# ─────────────── _month_range ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "year,month,expected_last",
    [
        (2026, 1, 31),
        (2025, 2, 28),  # non-leap February
        (2024, 2, 29),  # leap February
        (2026, 6, 30),
        (2026, 9, 30),
        (2026, 12, 31),
    ],
    ids=["january", "feb-nonleap", "feb-leap", "june", "september", "december"],
)
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


@pytest.mark.parametrize(
    "quarter,exp_start,exp_end",
    [
        (1, date(2026, 1, 1), date(2026, 3, 31)),
        (2, date(2026, 4, 1), date(2026, 6, 30)),
        (3, date(2026, 7, 1), date(2026, 9, 30)),
        (4, date(2026, 10, 1), date(2026, 12, 31)),
    ],
    ids=["Q1", "Q2", "Q3", "Q4"],
)
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


@pytest.mark.parametrize(
    "month,expected_name",
    [
        (1, "January"),
        (2, "February"),
        (3, "March"),
        (6, "June"),
        (9, "September"),
        (12, "December"),
    ],
    ids=["jan", "feb", "mar", "jun", "sep", "dec"],
)
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
    row = MonthlyRow(
        month=6, year=2026, worked_hours=7.5, target_hours=8.0, balance=-0.5
    )
    assert row.month == 6
    assert row.year == 2026
    assert row.worked_hours == pytest.approx(7.5)
    assert row.target_hours == pytest.approx(8.0)
    assert row.balance == pytest.approx(-0.5)


def test_monthly_row_positive_balance():
    row = MonthlyRow(
        month=1, year=2026, worked_hours=9.0, target_hours=8.0, balance=1.0
    )
    assert row.balance == pytest.approx(1.0)
    assert row.worked_hours > row.target_hours


# ─────────────── period_summary() — empty database ───────────────────────────


def test_period_summary_month_empty_db_zeroes(period_models):
    tc, vac, sick, sm = period_models
    data = period_summary(
        "month",
        2026,
        month=6,
        quarter=None,
        model_tc=tc,
        model_vacation=vac,
        model_sickness=sick,
        settings=sm,
    )
    assert data.worked_hours == pytest.approx(0.0)
    assert data.target_hours == pytest.approx(0.0)
    assert data.time_balance == pytest.approx(0.0)
    assert data.monthly_rows == []


def test_period_summary_month_stores_metadata(period_models):
    tc, vac, sick, sm = period_models
    data = period_summary(
        "month",
        2026,
        month=3,
        quarter=None,
        model_tc=tc,
        model_vacation=vac,
        model_sickness=sick,
        settings=sm,
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
        "quarter",
        2026,
        month=None,
        quarter=2,
        model_tc=tc,
        model_vacation=vac,
        model_sickness=sick,
        settings=sm,
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
        "quarter",
        2026,
        month=None,
        quarter=1,
        model_tc=tc,
        model_vacation=vac,
        model_sickness=sick,
        settings=sm,
    )
    for row in data.monthly_rows:
        assert row.year == 2026


def test_period_summary_quarter_empty_db_rows_zero(period_models):
    tc, vac, sick, sm = period_models
    data = period_summary(
        "quarter",
        2026,
        month=None,
        quarter=3,
        model_tc=tc,
        model_vacation=vac,
        model_sickness=sick,
        settings=sm,
    )
    for row in data.monthly_rows:
        assert row.worked_hours == 0.0
        assert row.target_hours == 0.0


def test_period_summary_quarter_missing_quarter_raises(period_models):
    """End-to-end: period_summary("quarter", quarter=None) must raise
    ValueError, not silently misbehave. (Today this is actually caught
    first by period_range()'s own quarter=None guard, called earlier in
    period_summary -- see the more targeted test below for the separate
    guard added at the former `# type: ignore[arg-type]` site.)"""
    tc, vac, sick, sm = period_models
    with pytest.raises(ValueError, match="quarter is required"):
        period_summary(
            "quarter",
            2026,
            month=None,
            quarter=None,
            model_tc=tc,
            model_vacation=vac,
            model_sickness=sick,
            settings=sm,
        )


def test_period_summary_monthly_breakdown_guard_raises_independently_of_period_range(
    period_models, monkeypatch
):
    """Regression guard for the `_quarter_months(quarter)  # type: ignore[arg-type]`
    removal in period_summary's monthly-breakdown branch. That call site now
    has its own `if quarter is None: raise ValueError(...)` guard, matching
    period_range's existing pattern. Bypass period_range's own earlier
    quarter=None check (via monkeypatch) to prove the *new* guard is
    independently correct, not just unreachable dead code shadowed by the
    pre-existing check."""
    tc, vac, sick, sm = period_models

    monkeypatch.setattr(
        report_module,
        "period_range",
        lambda period_type, year, month, quarter: (date(2026, 7, 1), date(2026, 9, 30)),
    )

    with pytest.raises(ValueError, match="quarter is required"):
        period_summary(
            "quarter",
            2026,
            month=None,
            quarter=None,
            model_tc=tc,
            model_vacation=vac,
            model_sickness=sick,
            settings=sm,
        )


def test_period_summary_year_has_twelve_rows(period_models):
    tc, vac, sick, sm = period_models
    data = period_summary(
        "year",
        2026,
        month=None,
        quarter=None,
        model_tc=tc,
        model_vacation=vac,
        model_sickness=sick,
        settings=sm,
    )
    assert data.period_type == "year"
    assert data.year == 2026
    assert data.month is None
    assert data.quarter is None
    assert len(data.monthly_rows) == 12
    assert [row.month for row in data.monthly_rows] == list(range(1, 13))


# ─────────── Monthly-breakdown regression (O(13N) -> O(N) refactor) ─────────


def test_period_summary_year_monthly_rows_match_independent_per_month_balance(
    period_models,
) -> None:
    """period_summary()'s monthly-breakdown loop now groups the year's
    records once (group_records_by_date) and slices per month via
    period_balance_from_grouped(), instead of re-scanning the full record
    list on every one of the (up to 13) calculate_period_balance() calls.
    This must be a pure performance refactor: every MonthlyRow (and the
    overall bal) must be bit-for-bit identical to computing each month's
    balance independently with calculate_period_balance() on the same raw
    records list."""
    tc, vac, sick, sm = period_models
    tc.save_work_day_targets({0: 8.0, 1: 8.0, 2: 8.0, 3: 8.0, 4: 8.0, 5: 0.0, 6: 0.0})

    # Records spread across several months of 2026, including an overtime
    # month (Feb) and a deficit month (Mar), so the balances aren't all zero.
    tc.insert_record(
        TimeRecord(None, date(2026, 1, 5), time(9, 0), time(17, 0), 0, WorkType.REMOTE)
    )
    tc.insert_record(
        TimeRecord(None, date(2026, 2, 10), time(8, 0), time(19, 0), 0, WorkType.REMOTE)
    )
    tc.insert_record(
        TimeRecord(None, date(2026, 3, 3), time(9, 0), time(13, 0), 0, WorkType.REMOTE)
    )
    tc.insert_record(
        TimeRecord(
            None,
            date(2026, 6, 15),
            time(9, 0),
            time(17, 30),
            15,
            WorkType.IN_SITE,
            office="HQ",
        )
    )

    data = period_summary(
        "year",
        2026,
        month=None,
        quarter=None,
        model_tc=tc,
        model_vacation=vac,
        model_sickness=sick,
        settings=sm,
    )

    # Independently recompute each month's balance directly, from a fresh
    # full-year fetch, exactly like the pre-refactor code path did.
    raw_records = tc.get_records_for_period(2026)
    targets = tc.get_work_day_targets()
    exceptions = {d.date: d.hours for d in tc.get_date_exceptions(2026)}
    overtime_rate = float(sm.get("overtime_rate", 1.0))

    assert len(data.monthly_rows) == 12
    for row in data.monthly_rows:
        m_start, m_end = _month_range(2026, row.month)
        expected = calculate_period_balance(
            raw_records,
            m_start,
            m_end,
            targets,
            exceptions,
            overtime_rate,
        )
        assert row.worked_hours == pytest.approx(expected.worked_hours)
        assert row.target_hours == pytest.approx(expected.target_hours)
        assert row.balance == pytest.approx(expected.balance)

    overall_expected = calculate_period_balance(
        raw_records,
        date(2026, 1, 1),
        date(2026, 12, 31),
        targets,
        exceptions,
        overtime_rate,
    )
    assert data.worked_hours == pytest.approx(overall_expected.worked_hours)
    assert data.target_hours == pytest.approx(overall_expected.target_hours)
    assert data.time_balance == pytest.approx(overall_expected.balance)
    assert data.weighted_overtime == pytest.approx(overall_expected.weighted_overtime)


def test_period_summary_vac_defaults_with_no_settings(period_models):
    tc, vac, sick, sm = period_models
    data = period_summary(
        "month",
        2026,
        month=6,
        quarter=None,
        model_tc=tc,
        model_vacation=vac,
        model_sickness=sick,
        settings=sm,
    )
    # No vacation settings set → allowance and pool are 0.0
    assert data.vac_allowance == pytest.approx(0.0)
    assert data.vac_used == pytest.approx(0.0)
    assert data.vac_remaining == pytest.approx(0.0)
    # No sickness settings set → default fallback is 80.0h (10 days × 8h)
    assert data.sick_allowance_hours == pytest.approx(80.0)
    assert data.sick_used_hours == pytest.approx(0.0)


# ─────────── skipped_record_count ────────────────────────────────────────────


def test_period_summary_no_skipped_records_is_zero(period_models):
    """The common case: no malformed rows anywhere → skipped_record_count
    must be exactly 0, not merely falsy, so callers don't spuriously warn."""
    tc, vac, sick, sm = period_models
    good = TimeRecord(
        None, date(2026, 6, 26), time(9, 0), time(17, 0), 30, WorkType.REMOTE
    )
    tc.insert_record(good)

    data = period_summary(
        "month",
        2026,
        month=6,
        quarter=None,
        model_tc=tc,
        model_vacation=vac,
        model_sickness=sick,
        settings=sm,
    )
    assert data.skipped_record_count == 0


def test_period_summary_counts_malformed_time_clock_row(period_models):
    """A malformed time_record row (dropped by TimeClockModel._row_to_record())
    must be reflected in ReportData.skipped_record_count so report_dialog.py
    can warn the user instead of silently presenting an incomplete report."""
    tc, vac, sick, sm = period_models
    conn = tc.db.get_connection()
    try:
        with conn:
            # break_minutes (600) exceeds the shift length -> fails the
            # TimeRecord invariant, same technique used in
            # tests/models/test_time_clock_model.py.
            conn.execute(
                "INSERT INTO time_record "
                "(date, start_time, end_time, break_minutes, work_type) "
                "VALUES ('2026-06-26', '09:00', '10:00', 600, 'remote');"
            )
    finally:
        conn.close()

    data = period_summary(
        "month",
        2026,
        month=6,
        quarter=None,
        model_tc=tc,
        model_vacation=vac,
        model_sickness=sick,
        settings=sm,
    )
    assert data.skipped_record_count == 1


def test_period_summary_sums_skipped_records_across_all_four_models(
    period_models, event_bus, db
):
    """skipped_record_count must be the sum across time clock, vacation,
    sickness, *and* miliuim -- a report can pull from all four models, and
    an earlier model's skip must not be overwritten by a later model's
    (zero) count."""
    from models.miliuim_model import MiliuimModel

    tc, vac, sick, sm = period_models
    miliuim = MiliuimModel(db, event_bus)

    conn = db.get_connection()
    try:
        with conn:
            # time_record: break_minutes exceeds shift length.
            conn.execute(
                "INSERT INTO time_record "
                "(date, start_time, end_time, break_minutes, work_type) "
                "VALUES ('2026-06-26', '09:00', '10:00', 600, 'remote');"
            )
            # vacation_record: note exceeds the 500-char limit.
            conn.execute(
                "INSERT INTO vacation_record (date, hours, vtype, note) "
                "VALUES ('2026-06-01', 4.0, 'annual_leave', ?);",
                ("x" * 501,),
            )
            # sickness_record: note exceeds the 500-char limit.
            conn.execute(
                "INSERT INTO sickness_record (date, hours, note) "
                "VALUES ('2026-06-02', 8.0, ?);",
                ("x" * 501,),
            )
            # miliuim_period: note exceeds the 500-char limit. (end_date <
            # start_date is rejected by the table's own CHECK constraint
            # before it ever reaches MiliuimRecord's validation, so an
            # overlong note is used here instead, mirroring vacation/
            # sickness above.)
            conn.execute(
                "INSERT INTO miliuim_period (start_date, end_date, note) "
                "VALUES ('2026-06-10', '2026-06-12', ?);",
                ("x" * 501,),
            )
    finally:
        conn.close()

    data = period_summary(
        "year",
        2026,
        month=None,
        quarter=None,
        model_tc=tc,
        model_vacation=vac,
        model_sickness=sick,
        settings=sm,
        model_miliuim=miliuim,
    )
    assert data.skipped_record_count == 4
