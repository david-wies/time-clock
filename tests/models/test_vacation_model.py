import pytest
from datetime import date, datetime
from domain.types import VacationRecord
from domain.enums import VacationType
from models.vacation_model import VacationModel
from models.time_clock_model import TimeClockModel
from core.events import EventBus, Event
from db.database import Database


def test_vacation_events(db: Database, event_bus: EventBus) -> None:
    model = VacationModel(db, event_bus)

    change_called = False

    def on_change() -> None:
        nonlocal change_called
        change_called = True

    event_bus.subscribe(Event.VACATION_CHANGED, on_change)

    rec = VacationRecord(None, date(2026, 7, 15), 8.0,
                         VacationType.ANNUAL_LEAVE)
    rec_id = model.insert_record(rec)
    assert change_called is True

    change_called = False
    fetched = model.get_record_by_id(rec_id)
    assert fetched is not None
    fetched.hours = 4.0
    model.update_record(fetched)
    assert change_called is True

    change_called = False
    model.delete_record(rec_id)
    assert change_called is True


@pytest.mark.parametrize(
    "year, month, expected_last_day",
    [
        (2024, 2, 29),  # leap-year February
        (2026, 2, 28),  # non-leap-year February
        (2026, 4, 30),  # 30-day month
    ],
)
def test_get_records_for_year_uses_real_month_end_date(
    db: Database, event_bus: EventBus, year: int, month: int, expected_last_day: int
) -> None:
    """Regression guard for the `f"{year:04d}-{month:02d}-31"` hardcoding
    bug: the query's end-of-month bound must be the real last day of the
    month (via calendar.monthrange), not a literal "-31" that happens to
    still sort correctly by lexicographic accident. Captures the actual
    bound SQLite receives via set_trace_callback (which expands bound
    parameters into the executed SQL text)."""
    model = VacationModel(db, event_bus)
    conn = db.get_connection()

    captured_statements: list[str] = []
    conn.set_trace_callback(captured_statements.append)
    try:
        model.get_records_for_year(year, month=month)
    finally:
        conn.set_trace_callback(None)

    select_statements = [
        s for s in captured_statements if s.startswith("SELECT * FROM vacation_record")]
    assert len(select_statements) == 1
    expected_end_date = f"{year:04d}-{month:02d}-{expected_last_day:02d}"
    assert expected_end_date in select_statements[0]
    if expected_last_day != 31:
        assert f"{year:04d}-{month:02d}-31" not in select_statements[0]


def test_vacation_record_crud(db: Database, event_bus: EventBus) -> None:
    model = VacationModel(db, event_bus)

    rec = VacationRecord(
        id=None,
        date=date(2026, 7, 15),
        hours=8.0,
        vtype=VacationType.ANNUAL_LEAVE,
        note="Summer vacation"
    )

    # Insert
    rec_id = model.insert_record(rec)
    assert rec_id > 0

    # Get
    fetched = model.get_record_by_id(rec_id)
    assert fetched is not None
    assert fetched.hours == 8.0
    assert fetched.vtype == VacationType.ANNUAL_LEAVE

    # Update
    fetched.hours = 4.0
    fetched.vtype = VacationType.SPECIAL_LEAVE
    model.update_record(fetched)

    updated = model.get_record_by_id(rec_id)
    assert updated.hours == 4.0
    assert updated.vtype == VacationType.SPECIAL_LEAVE

    # Delete
    model.delete_record(rec_id)
    assert model.get_record_by_id(rec_id) is None


def test_vacation_settings(db: Database, event_bus: EventBus) -> None:
    model = VacationModel(db, event_bus)

    model.save_settings(2026, 160.0, 40.0)
    settings = model.get_settings(2026)
    assert settings is not None
    assert settings["hours_per_year"] == 160.0
    assert settings["max_carry_over"] == 40.0

    assert model.get_settings(2025) is None


def test_unpaid_leave_not_counted_as_used(db: Database, event_bus: EventBus) -> None:
    model = VacationModel(db, event_bus)
    model.save_settings(2026, 160.0, 40.0)

    rec = VacationRecord(None, date(2026, 7, 1), 8.0,
                         VacationType.UNPAID_LEAVE)
    model.insert_record(rec)

    summary = model.calculate_vacation_summary(2026)
    assert summary.used == 0.0
    assert summary.remaining == 160.0


def test_calculate_vacation_summary_combines_carry_over_and_used_in_one_query(
    db: Database, event_bus: EventBus
) -> None:
    """calculate_vacation_summary() combines the carry-over-credit and
    used-debit SUMs into a single conditional-aggregation query instead of
    two sequential SELECT SUM(...) queries -- this test exercises a year
    with *both* record kinds present simultaneously to confirm the
    combined query still attributes hours to the right bucket."""
    model = VacationModel(db, event_bus)
    model.save_settings(2026, 160.0, 40.0)

    model.insert_record(
        VacationRecord(None, date(2026, 1, 1), 15.0, VacationType.CARRY_OVER))
    model.insert_record(
        VacationRecord(None, date(2026, 3, 10), 24.0, VacationType.ANNUAL_LEAVE))
    model.insert_record(
        VacationRecord(None, date(2026, 5, 5), 8.0, VacationType.PUBLIC_HOLIDAY))
    model.insert_record(
        VacationRecord(None, date(2026, 8, 20), 16.0, VacationType.SPECIAL_LEAVE))
    # Not counted as "used" -- must not leak into either bucket.
    model.insert_record(
        VacationRecord(None, date(2026, 9, 1), 40.0, VacationType.UNPAID_LEAVE))

    summary = model.calculate_vacation_summary(2026)

    assert summary.allowance == 160.0
    assert summary.carry_over == 15.0
    assert summary.total_pool == 175.0
    assert summary.used == 48.0  # 24 + 8 + 16
    assert summary.remaining == 127.0  # 175 - 48


def test_vacation_balance_and_carry_over(db: Database, event_bus: EventBus) -> None:
    model = VacationModel(db, event_bus)

    # 1. Setup settings
    # Prev year (2025): allowance=160h, max carryover=40h
    # Target year (2026): allowance=160h, max carryover=40h
    model.save_settings(2025, 160.0, 40.0)
    model.save_settings(2026, 160.0, 40.0)

    # 2. Add some used vacation in 2025
    # Total used in 2025: 140h (so 20h remaining)
    r1 = VacationRecord(None, date(2025, 6, 1), 120.0,
                        VacationType.ANNUAL_LEAVE)
    r2 = VacationRecord(None, date(2025, 12, 25), 20.0,
                        VacationType.PUBLIC_HOLIDAY)
    model.insert_record(r1)
    model.insert_record(r2)

    summary_2025 = model.calculate_vacation_summary(2025)
    assert summary_2025.remaining == 20.0

    # 3. Calculate carry-over allowance for 2026 (from 2025 surplus)
    # Surplus: 20h, Max carry-over: 40h, Already transferred: 0h. Allowed: 20h.
    allowance = model.calculate_carry_over_allowance(2026)
    assert allowance.prev_surplus == 20.0
    assert allowance.allowed_transfer == 20.0
    assert allowance.already_transferred == 0.0

    # 4. Perform carry over of 15 hours
    model.add_carry_over(2025, 2026, 15.0)

    # 5. Check audit logs and summary
    assert model.get_already_transferred(2025, 2026) == 15.0

    # 2026 summary should show 15h carry_over credit
    summary_2026 = model.calculate_vacation_summary(2026)
    assert summary_2026.allowance == 160.0
    assert summary_2026.carry_over == 15.0
    assert summary_2026.total_pool == 175.0
    assert summary_2026.remaining == 175.0  # no debits yet

    # 6. Recalculate carry over allowance for 2026 (to check clamping)
    # Surplus: 20h, Max carryover: 40h, Already transferred: 15h. Allowed remaining: 5h.
    allowance_after = model.calculate_carry_over_allowance(2026)
    assert allowance_after.allowed_transfer == 5.0
    assert allowance_after.already_transferred == 15.0


def test_carry_over_history(db: Database, event_bus: EventBus) -> None:
    model = VacationModel(db, event_bus)

    model.save_settings(2025, 160.0, 40.0)
    model.save_settings(2026, 160.0, 40.0)

    # Use only 145h of 160h in 2025 (15h remaining)
    r1 = VacationRecord(None, date(2025, 6, 1), 145.0,
                        VacationType.ANNUAL_LEAVE)
    model.insert_record(r1)

    model.add_carry_over(2025, 2026, 15.0)

    history = model.get_carry_over_history(2026)
    assert len(history) == 1
    assert history[0].hours == 15.0
    assert history[0].from_year == 2025
    assert isinstance(history[0].transferred_at, datetime)


def test_daily_target_falls_back_to_weekday(db: Database, event_bus: EventBus) -> None:
    model = VacationModel(db, event_bus)
    tc_model = TimeClockModel(db, event_bus)
    tc_model.save_work_day_targets({0: 9.0, 1: 7.5})

    monday = date(2026, 6, 22)  # weekday() == 0
    assert monday.weekday() == 0
    assert model.get_daily_target_for_date(monday) == 9.0


def test_daily_target_uses_date_exception_over_weekday(db: Database, event_bus: EventBus) -> None:
    model = VacationModel(db, event_bus)
    tc_model = TimeClockModel(db, event_bus)
    tc_model.save_work_day_targets({0: 9.0})

    exception_date = date(2026, 6, 22)  # a Monday, normally 9.0h
    tc_model.save_date_exception(
        exception_date.isoformat(), 4.0, "Short Friday-eve")

    assert model.get_daily_target_for_date(exception_date) == 4.0
    # A day without an exception still falls back to the weekday target.
    assert model.get_daily_target_for_date(date(2026, 6, 29)) == 9.0
