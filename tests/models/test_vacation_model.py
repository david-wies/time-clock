import dataclasses
import logging
from datetime import date, datetime

import pytest

from core.events import Event, EventBus
from db.database import Database
from domain.enums import VacationType
from domain.types import VacationRecord
from models.errors import RecordNotFoundError
from models.time_clock_model import TimeClockModel
from models.vacation_model import VacationModel


def test_vacation_events(db: Database, event_bus: EventBus) -> None:
    model = VacationModel(db, event_bus)

    change_called = False

    def on_change() -> None:
        nonlocal change_called
        change_called = True

    event_bus.subscribe(Event.VACATION_CHANGED, on_change)

    rec = VacationRecord(None, date(2026, 7, 15), 8.0, VacationType.ANNUAL_LEAVE)
    rec_id = model.insert_record(rec)
    assert change_called is True

    change_called = False
    fetched = model.get_record_by_id(rec_id)
    assert fetched is not None
    # VacationRecord is frozen (domain/types.py) -- dataclasses.replace()
    # builds a new, revalidated instance instead of mutating in place.
    fetched = dataclasses.replace(fetched, hours=4.0)
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
        s for s in captured_statements if s.startswith("SELECT * FROM vacation_record")
    ]
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
        note="Summer vacation",
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
    fetched = dataclasses.replace(fetched, hours=4.0, vtype=VacationType.SPECIAL_LEAVE)
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

    rec = VacationRecord(None, date(2026, 7, 1), 8.0, VacationType.UNPAID_LEAVE)
    model.insert_record(rec)

    summary = model.calculate_vacation_summary(2026)
    assert summary.used == 0.0
    assert summary.remaining == 160.0


def test_calculate_vacation_summary_sums_carry_over_and_used_from_one_fetch(
    db: Database, event_bus: EventBus
) -> None:
    """calculate_vacation_summary() sums the carry-over-credit and used-debit
    buckets from a single get_records_for_year() fetch (the same row-fetch
    method -- and malformed-row-skip behavior -- every other reader in this
    model uses), instead of issuing its own separate query per bucket. This
    test exercises a year with *both* record kinds present simultaneously to
    confirm the shared fetch still attributes hours to the right bucket, and
    confirms only one SELECT is issued against vacation_record."""
    model = VacationModel(db, event_bus)
    model.save_settings(2026, 160.0, 40.0)

    model.insert_record(
        VacationRecord(None, date(2026, 1, 1), 15.0, VacationType.CARRY_OVER)
    )
    model.insert_record(
        VacationRecord(None, date(2026, 3, 10), 24.0, VacationType.ANNUAL_LEAVE)
    )
    model.insert_record(
        VacationRecord(None, date(2026, 5, 5), 8.0, VacationType.PUBLIC_HOLIDAY)
    )
    model.insert_record(
        VacationRecord(None, date(2026, 8, 20), 16.0, VacationType.SPECIAL_LEAVE)
    )
    # Not counted as "used" -- must not leak into either bucket.
    model.insert_record(
        VacationRecord(None, date(2026, 9, 1), 40.0, VacationType.UNPAID_LEAVE)
    )

    conn = db.get_connection()
    captured_statements: list[str] = []
    conn.set_trace_callback(captured_statements.append)
    try:
        summary = model.calculate_vacation_summary(2026)
    finally:
        conn.set_trace_callback(None)

    select_statements = [
        s for s in captured_statements if s.startswith("SELECT * FROM vacation_record")
    ]
    assert len(select_statements) == 1

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
    r1 = VacationRecord(None, date(2025, 6, 1), 120.0, VacationType.ANNUAL_LEAVE)
    r2 = VacationRecord(None, date(2025, 12, 25), 20.0, VacationType.PUBLIC_HOLIDAY)
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
    r1 = VacationRecord(None, date(2025, 6, 1), 145.0, VacationType.ANNUAL_LEAVE)
    model.insert_record(r1)

    model.add_carry_over(2025, 2026, 15.0)

    history = model.get_carry_over_history(2026)
    assert len(history) == 1
    assert history[0].hours == 15.0
    assert history[0].from_year == 2025
    assert isinstance(history[0].transferred_at, datetime)


def test_update_record_without_id_raises(db: Database, event_bus: EventBus) -> None:
    """update_record() requires a persisted id -- a record that was never
    inserted (id=None) cannot be targeted by an UPDATE ... WHERE id = ?
    statement, so this is checked explicitly rather than silently updating
    zero rows."""
    model = VacationModel(db, event_bus)
    rec = VacationRecord(None, date(2026, 7, 15), 8.0, VacationType.ANNUAL_LEAVE)

    with pytest.raises(ValueError, match="Cannot update a record without an ID"):
        model.update_record(rec)


def test_delete_record_nonexistent_id_raises(db: Database, event_bus: EventBus) -> None:
    """delete_record() must not silently succeed (and publish
    VACATION_CHANGED) for an id that was never persisted or was already
    deleted -- mirrors the rowcount-based guard already in update_record()."""
    model = VacationModel(db, event_bus)

    change_called = False

    def on_change() -> None:
        nonlocal change_called
        change_called = True

    event_bus.subscribe(Event.VACATION_CHANGED, on_change)

    with pytest.raises(
        RecordNotFoundError, match="No vacation_record with id=999 exists to delete"
    ):
        model.delete_record(999)

    assert change_called is False


def test_update_record_on_since_deleted_record_raises(
    db: Database, event_bus: EventBus
) -> None:
    """update_record() called with a stale record object -- one whose id was
    deleted out from under it (e.g. a view that fetched a record and hasn't
    refreshed since another path deleted it) -- must raise rather than
    silently no-op, exactly like delete_record()'s own rowcount guard."""
    model = VacationModel(db, event_bus)
    rec = VacationRecord(None, date(2026, 7, 15), 8.0, VacationType.ANNUAL_LEAVE)
    rec_id = model.insert_record(rec)
    fetched = model.get_record_by_id(rec_id)
    assert fetched is not None

    model.delete_record(rec_id)

    change_called = False

    def on_change() -> None:
        nonlocal change_called
        change_called = True

    event_bus.subscribe(Event.VACATION_CHANGED, on_change)

    stale = dataclasses.replace(fetched, hours=4.0)
    with pytest.raises(
        RecordNotFoundError,
        match=f"No vacation_record with id={rec_id} exists to update",
    ):
        model.update_record(stale)

    assert change_called is False


def test_get_carry_over_history_skips_malformed_year_gap_and_logs_warning(
    db: Database, event_bus: EventBus, caplog
) -> None:
    """A carry_over_log row whose from_year/to_year aren't exactly one year
    apart (e.g. from manual DB editing -- the DB schema has no CHECK
    constraint tying the two columns together, only `hours > 0`) fails
    CarryOverLogEntry's own cross-field __post_init__ check. This is a
    distinct failure mode from the malformed-`transferred_at` case covered
    by test_get_carry_over_history_skips_malformed_transferred_at_and_logs_warning
    -- here the row's own timestamp is fine, but the entry construction
    itself raises ValueError, which must be caught and skipped exactly like
    every other malformed-row-skip pattern in this model."""
    model = VacationModel(db, event_bus)
    model.save_settings(2025, 160.0, 40.0)
    model.save_settings(2026, 160.0, 40.0)
    model.add_carry_over(2025, 2026, 15.0)

    conn = db.get_connection()
    try:
        with conn:
            conn.execute(
                "INSERT INTO carry_over_log (from_year, to_year, hours) "
                "VALUES (2023, 2026, 5.0);"
            )
    finally:
        conn.close()

    with caplog.at_level(logging.WARNING, logger="models.vacation_model"):
        history = model.get_carry_over_history(2026)

    assert len(history) == 1
    assert history[0].hours == 15.0
    assert any(
        record.levelname == "WARNING" and "malformed" in record.message.lower()
        for record in caplog.records
    )


def test_calculate_carry_over_allowance_clamps_negative_prev_surplus_to_zero(
    db: Database, event_bus: EventBus
) -> None:
    """When the previous year's vacation summary is over-drawn (used hours
    exceed the total pool, e.g. an over-balance save that bypassed
    VacationController's guard by going straight through the model),
    `prev_summary.remaining` is negative -- calculate_carry_over_allowance()
    must clamp the carried-forward `surplus` to 0.0 rather than letting a
    negative surplus propagate (which would nonsensically reduce the next
    year's available carry-over below zero before the later clamps even
    apply)."""
    model = VacationModel(db, event_bus)
    model.save_settings(2025, 10.0, 0.0)
    model.save_settings(2026, 100.0, 100.0)

    over_drawn = VacationRecord(None, date(2025, 6, 1), 15.0, VacationType.ANNUAL_LEAVE)
    model.insert_record(over_drawn)
    assert model.calculate_vacation_summary(2025).remaining == -5.0

    allowance = model.calculate_carry_over_allowance(2026)

    assert allowance.prev_surplus == 0.0
    assert allowance.allowed_transfer == 0.0


def test_calculate_carry_over_allowance_clamps_negative_available_surplus_to_zero(
    db: Database, event_bus: EventBus
) -> None:
    """already_transferred can exceed the (non-negative) surplus if a
    caller logs a carry-over larger than what add_carry_over()'s own model
    layer allows (VacationController.add_carry_over()'s allowed_max guard
    lives one layer up, in the controller -- calling model.add_carry_over()
    directly, as here, bypasses it). available_surplus = surplus -
    already_transferred then goes negative and must clamp to 0.0."""
    model = VacationModel(db, event_bus)
    model.save_settings(2025, 10.0, 0.0)
    model.save_settings(2026, 100.0, 100.0)  # generous cap: isolates this clamp
    assert model.calculate_vacation_summary(2025).remaining == 10.0

    model.add_carry_over(2025, 2026, 15.0)  # exceeds the 10h surplus

    allowance = model.calculate_carry_over_allowance(2026)

    assert allowance.prev_surplus == 10.0
    assert allowance.already_transferred == 15.0
    assert allowance.available_surplus == 0.0
    assert allowance.allowed_transfer == 0.0


def test_calculate_carry_over_allowance_clamps_negative_allowed_transfer_to_zero(
    db: Database, event_bus: EventBus
) -> None:
    """already_transferred can also exceed max_carry_over alone, while
    staying within the (larger) surplus -- available_surplus then stays
    non-negative, isolating the final `allowed_transfer = min(max_carry_over
    - already_transferred, available_surplus)` clamp from the
    available_surplus clamp exercised above."""
    model = VacationModel(db, event_bus)
    model.save_settings(2025, 60.0, 0.0)
    model.save_settings(2026, 100.0, 10.0)  # max_carry_over = 10h
    assert model.calculate_vacation_summary(2025).remaining == 60.0

    model.add_carry_over(2025, 2026, 20.0)  # exceeds the 10h cap, not the 60h surplus

    allowance = model.calculate_carry_over_allowance(2026)

    assert allowance.available_surplus == 40.0  # not clamped: 60 - 20
    assert allowance.allowed_transfer == 0.0  # clamped: 10 - 20 = -10 -> 0


def test_daily_target_falls_back_to_weekday(db: Database, event_bus: EventBus) -> None:
    model = VacationModel(db, event_bus)
    tc_model = TimeClockModel(db, event_bus)
    tc_model.save_work_day_targets({0: 9.0, 1: 7.5})

    monday = date(2026, 6, 22)  # weekday() == 0
    assert monday.weekday() == 0
    assert model.get_daily_target_for_date(monday) == 9.0


def test_get_records_for_year_skips_malformed_row_and_logs_warning(
    db: Database, event_bus: EventBus, caplog
) -> None:
    """A row that violates a VacationRecord invariant at the DB level (e.g.
    a note longer than the domain's 500-char cap -- something no DB CHECK
    constraint enforces) must not crash the whole read. It should be logged
    and skipped, exactly like the malformed-date handling in
    TimeClockModel.get_date_exceptions()."""
    model = VacationModel(db, event_bus)

    good = VacationRecord(None, date(2026, 7, 15), 8.0, VacationType.ANNUAL_LEAVE, "ok")
    model.insert_record(good)

    conn = db.get_connection()
    try:
        with conn:
            conn.execute(
                "INSERT INTO vacation_record (date, hours, vtype, note) "
                "VALUES (?, ?, ?, ?);",
                ("2026-07-16", 4.0, "annual_leave", "x" * 501),
            )
    finally:
        conn.close()

    with caplog.at_level(logging.WARNING, logger="models.vacation_model"):
        records = model.get_records_for_year(2026)

    assert len(records) == 1
    assert records[0].note == "ok"
    assert model.last_skipped_count == 1
    assert any(
        record.levelname == "WARNING" and "malformed" in record.message.lower()
        for record in caplog.records
    )


def test_get_record_by_id_returns_none_for_malformed_row(
    db: Database, event_bus: EventBus, caplog
) -> None:
    """A single malformed row fetched by ID must return None (not raise),
    with a warning logged."""
    model = VacationModel(db, event_bus)

    conn = db.get_connection()
    try:
        with conn:
            cursor = conn.execute(
                "INSERT INTO vacation_record (date, hours, vtype, note) "
                "VALUES (?, ?, ?, ?);",
                ("2026-07-16", 4.0, "annual_leave", "x" * 501),
            )
            bad_id = cursor.lastrowid
    finally:
        conn.close()

    with caplog.at_level(logging.WARNING, logger="models.vacation_model"):
        result = model.get_record_by_id(bad_id)

    assert result is None
    assert any(
        record.levelname == "WARNING" and "malformed" in record.message.lower()
        for record in caplog.records
    )


def test_get_carry_over_history_skips_malformed_transferred_at_and_logs_warning(
    db: Database, event_bus: EventBus, caplog
) -> None:
    """An unparseable `transferred_at` value (e.g. from manual DB editing)
    must not crash get_carry_over_history() -- it should be logged and
    skipped, matching the defensive row-reconstruction pattern used
    elsewhere in this model."""
    model = VacationModel(db, event_bus)
    model.save_settings(2025, 160.0, 40.0)
    model.save_settings(2026, 160.0, 40.0)
    model.add_carry_over(2025, 2026, 15.0)

    conn = db.get_connection()
    try:
        with conn:
            conn.execute(
                "INSERT INTO carry_over_log "
                "(from_year, to_year, hours, transferred_at) "
                "VALUES (2025, 2026, 5.0, 'not-a-timestamp');"
            )
    finally:
        conn.close()

    with caplog.at_level(logging.WARNING, logger="models.vacation_model"):
        history = model.get_carry_over_history(2026)

    assert len(history) == 1
    assert history[0].hours == 15.0
    assert any(
        record.levelname == "WARNING" and "malformed" in record.message.lower()
        for record in caplog.records
    )


def test_daily_target_uses_date_exception_over_weekday(
    db: Database, event_bus: EventBus
) -> None:
    model = VacationModel(db, event_bus)
    tc_model = TimeClockModel(db, event_bus)
    tc_model.save_work_day_targets({0: 9.0})

    exception_date = date(2026, 6, 22)  # a Monday, normally 9.0h
    tc_model.save_date_exception(exception_date.isoformat(), 4.0, "Short Friday-eve")

    assert model.get_daily_target_for_date(exception_date) == 4.0
    # A day without an exception still falls back to the weekday target.
    assert model.get_daily_target_for_date(date(2026, 6, 29)) == 9.0
