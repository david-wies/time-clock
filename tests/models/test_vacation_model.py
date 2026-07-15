import dataclasses
import logging
from datetime import date, datetime

import pytest

from core.events import Event, EventBus
from db.database import Database
from domain.enums import VacationType
from domain.types import Hours, VacationGrant, VacationRecord
from models.errors import RecordNotFoundError
from models.time_clock_model import TimeClockModel
from models.vacation_model import VacationModel
from settings import SettingsManager


def test_vacation_events(db: Database, event_bus: EventBus) -> None:
    model = VacationModel(db, event_bus)

    change_called = False

    def on_change() -> None:
        nonlocal change_called
        change_called = True

    event_bus.subscribe(Event.VACATION_CHANGED, on_change)

    rec = VacationRecord(None, date(2026, 7, 15), Hours(8.0), VacationType.ANNUAL_LEAVE)
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
        hours=Hours(8.0),
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

    rec = VacationRecord(None, date(2026, 7, 1), Hours(8.0), VacationType.UNPAID_LEAVE)
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
        VacationRecord(None, date(2026, 1, 1), Hours(15.0), VacationType.CARRY_OVER)
    )
    model.insert_record(
        VacationRecord(None, date(2026, 3, 10), Hours(24.0), VacationType.ANNUAL_LEAVE)
    )
    model.insert_record(
        VacationRecord(None, date(2026, 5, 5), Hours(8.0), VacationType.PUBLIC_HOLIDAY)
    )
    model.insert_record(
        VacationRecord(None, date(2026, 8, 20), Hours(16.0), VacationType.SPECIAL_LEAVE)
    )
    # Not counted as "used" -- must not leak into either bucket.
    model.insert_record(
        VacationRecord(None, date(2026, 9, 1), Hours(40.0), VacationType.UNPAID_LEAVE)
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
    r1 = VacationRecord(None, date(2025, 6, 1), Hours(120.0), VacationType.ANNUAL_LEAVE)
    r2 = VacationRecord(
        None, date(2025, 12, 25), Hours(20.0), VacationType.PUBLIC_HOLIDAY
    )
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
    r1 = VacationRecord(None, date(2025, 6, 1), Hours(145.0), VacationType.ANNUAL_LEAVE)
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
    rec = VacationRecord(None, date(2026, 7, 15), Hours(8.0), VacationType.ANNUAL_LEAVE)

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
    rec = VacationRecord(None, date(2026, 7, 15), Hours(8.0), VacationType.ANNUAL_LEAVE)
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

    over_drawn = VacationRecord(
        None, date(2025, 6, 1), Hours(15.0), VacationType.ANNUAL_LEAVE
    )
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

    good = VacationRecord(
        None, date(2026, 7, 15), Hours(8.0), VacationType.ANNUAL_LEAVE, "ok"
    )
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


# ──────────── #47: charge-weighted `used` ───────────────────────────────────


def test_used_is_charge_weighted_half_rate(db: Database, event_bus: EventBus) -> None:
    """A debit record with charge_rate=0.5 spends only half its hours against
    the year's pool: `used` is sum(hours * charge_rate), so an 8h day at 0.5
    contributes 4.0 to `used` (and total_pool/remaining reflect only that
    charge-weighted cost)."""
    model = VacationModel(db, event_bus)
    model.save_settings(2026, 160.0, 40.0)
    model.insert_record(
        VacationRecord(
            None,
            date(2026, 3, 10),
            Hours(8.0),
            VacationType.ANNUAL_LEAVE,
            charge_rate=0.5,
        )
    )

    summary = model.calculate_vacation_summary(2026)

    assert summary.used == 4.0
    assert summary.total_pool == 160.0
    assert summary.remaining == 156.0


def test_used_charge_weight_mix_full_half_and_zero(
    db: Database, event_bus: EventBus
) -> None:
    """Charge weighting is applied per debit record: rate=1.0 bills the full
    hours, rate=0.5 bills half, rate=0.0 bills nothing. Three 8h debit records
    at those rates sum to 8 + 4 + 0 = 12 charge-weighted `used` hours."""
    model = VacationModel(db, event_bus)
    model.save_settings(2026, 160.0, 40.0)
    model.insert_record(
        VacationRecord(
            None,
            date(2026, 1, 5),
            Hours(8.0),
            VacationType.ANNUAL_LEAVE,
            charge_rate=1.0,
        )
    )
    model.insert_record(
        VacationRecord(
            None,
            date(2026, 2, 5),
            Hours(8.0),
            VacationType.SPECIAL_LEAVE,
            charge_rate=0.5,
        )
    )
    model.insert_record(
        VacationRecord(
            None,
            date(2026, 3, 5),
            Hours(8.0),
            VacationType.PUBLIC_HOLIDAY,
            charge_rate=0.0,
        )
    )

    summary = model.calculate_vacation_summary(2026)

    assert summary.used == 12.0  # 8*1.0 + 8*0.5 + 8*0.0
    assert summary.remaining == 148.0  # 160 - 12


@pytest.mark.parametrize("rate", [-0.1, -1.0, 1.1, 1.5])
def test_vacation_record_rejects_charge_rate_out_of_range(rate: float) -> None:
    """The 0.0..1.0 charge_rate bound is a context-free invariant enforced at
    construction (via vacation_record_invariant_errors / __post_init__), so a
    rate below 0 or above 1 raises immediately."""
    with pytest.raises(ValueError, match="Charge rate must be between 0.0 and 1.0."):
        VacationRecord(
            None,
            date(2026, 7, 15),
            Hours(8.0),
            VacationType.ANNUAL_LEAVE,
            charge_rate=rate,
        )


@pytest.mark.parametrize("rate", [0.0, 0.5, 1.0])
def test_vacation_record_accepts_charge_rate_in_range(rate: float) -> None:
    """The boundary rates 0.0 and 1.0 (and anything between) are accepted."""
    rec = VacationRecord(
        None, date(2026, 7, 15), Hours(8.0), VacationType.ANNUAL_LEAVE, charge_rate=rate
    )
    assert rec.charge_rate == rate


# ──────────── #47: vacation grants (CRUD + pooling) ─────────────────────────


def test_vacation_grant_crud(db: Database, event_bus: EventBus) -> None:
    """Grant insert/update/delete round-trips through its own vacation_grant
    table, mirroring the vacation_record CRUD surface."""
    model = VacationModel(db, event_bus)

    grant = VacationGrant(None, date(2026, 6, 1), Hours(12.0), note="Signing bonus")
    grant_id = model.insert_grant(grant)
    assert grant_id > 0

    fetched = model.get_grant_by_id(grant_id)
    assert fetched is not None
    assert fetched.hours == 12.0
    assert fetched.note == "Signing bonus"

    updated = dataclasses.replace(fetched, hours=6.0)
    model.update_grant(updated)
    reread = model.get_grant_by_id(grant_id)
    assert reread is not None
    assert reread.hours == 6.0

    model.delete_grant(grant_id)
    assert model.get_grant_by_id(grant_id) is None


def test_vacation_grant_events(db: Database, event_bus: EventBus) -> None:
    """Every grant mutation publishes VACATION_CHANGED, matching the
    vacation_record CRUD event contract."""
    model = VacationModel(db, event_bus)

    change_called = False

    def on_change() -> None:
        nonlocal change_called
        change_called = True

    event_bus.subscribe(Event.VACATION_CHANGED, on_change)

    grant = VacationGrant(None, date(2026, 6, 1), Hours(12.0))
    grant_id = model.insert_grant(grant)
    assert change_called is True

    change_called = False
    fetched = model.get_grant_by_id(grant_id)
    assert fetched is not None
    model.update_grant(dataclasses.replace(fetched, hours=4.0))
    assert change_called is True

    change_called = False
    model.delete_grant(grant_id)
    assert change_called is True


def test_get_grants_for_year_filters_and_extra_grant_pools(
    db: Database, event_bus: EventBus
) -> None:
    """get_grants_for_year(year) returns only that year's grants, and their
    total feeds VacationSummary.extra_grant, enlarging base_pool/total_pool. A
    grant dated in another year must not leak into either."""
    model = VacationModel(db, event_bus)
    model.save_settings(2026, 100.0, 0.0)

    model.insert_grant(VacationGrant(None, date(2026, 3, 1), Hours(10.0)))
    model.insert_grant(VacationGrant(None, date(2026, 9, 1), Hours(5.0)))
    # A grant in the previous year must not leak into 2026's pool.
    model.insert_grant(VacationGrant(None, date(2025, 12, 31), Hours(99.0)))

    grants_2026 = model.get_grants_for_year(2026)
    assert len(grants_2026) == 2
    assert all(g.date.year == 2026 for g in grants_2026)
    assert sum(g.hours for g in grants_2026) == 15.0

    summary = model.calculate_vacation_summary(2026)
    assert summary.extra_grant == 15.0
    assert summary.base_pool == 115.0  # 100 allowance + 0 carry + 15 grants
    assert summary.total_pool == 115.0  # no borrowing configured
    assert summary.remaining == 115.0  # no debits yet


# ──────────── #47: one-hop borrow-forward (borrowed_prev) ───────────────────


def test_get_max_borrow_hours_default_and_roundtrip(
    db: Database, event_bus: EventBus, settings_manager: SettingsManager
) -> None:
    """get_max_borrow_hours() defaults to 0.0 (no borrowing) when the
    app_config key is absent, and reads back the JSON-serialized value once
    SettingsManager writes it."""
    model = VacationModel(db, event_bus)
    assert model.get_max_borrow_hours() == 0.0

    settings_manager.set("vacation.max_borrow_hours", 12.5)
    assert model.get_max_borrow_hours() == 12.5


@pytest.mark.parametrize(
    "prev_used, max_borrow, expected_borrow",
    [
        (30.0, 15.0, 15.0),  # overage 20 -> capped at max_borrow 15
        (13.0, 15.0, 3.0),  # overage 3 -> below cap, borrows the overage
        (8.0, 15.0, 0.0),  # used < base_pool -> no overage, no borrow
    ],
    ids=["capped", "under-cap", "no-overage"],
)
def test_borrow_prev_is_min_of_overage_and_cap(
    db: Database,
    event_bus: EventBus,
    settings_manager: SettingsManager,
    prev_used: float,
    max_borrow: float,
    expected_borrow: float,
) -> None:
    """With a non-zero max_borrow, a year's borrowed_prev equals
    min(prev_year_overage, max_borrow), where the prior year's overage is
    max(0, prev.used - prev.base_pool). 2025 has base_pool = 10 (allowance 10,
    no carry/grants), so borrowed_prev for 2026 depends only on 2025's usage
    and the cap. borrowed_prev shrinks this year's total_pool."""
    model = VacationModel(db, event_bus)
    settings_manager.set("vacation.max_borrow_hours", max_borrow)
    model.save_settings(2025, 10.0, 0.0)
    model.save_settings(2026, 100.0, 0.0)
    model.insert_record(
        VacationRecord(
            None, date(2025, 6, 1), Hours(prev_used), VacationType.ANNUAL_LEAVE
        )
    )

    summary = model.calculate_vacation_summary(2026)

    assert summary.borrowed_prev == expected_borrow
    assert summary.base_pool == 100.0
    assert summary.total_pool == 100.0 - expected_borrow
    assert summary.remaining == 100.0 - expected_borrow


def test_borrow_disabled_when_max_borrow_zero(
    db: Database, event_bus: EventBus
) -> None:
    """Backward-compat guard: with max_borrow at its 0.0 default, borrowed_prev
    is always 0 even when the prior year is heavily over-drawn, so total_pool
    reduces to allowance + carry_over exactly as before #47."""
    model = VacationModel(db, event_bus)
    assert model.get_max_borrow_hours() == 0.0
    model.save_settings(2025, 10.0, 0.0)
    model.save_settings(2026, 100.0, 0.0)
    model.insert_record(
        VacationRecord(None, date(2025, 6, 1), Hours(30.0), VacationType.ANNUAL_LEAVE)
    )

    summary = model.calculate_vacation_summary(2026)

    assert summary.borrowed_prev == 0.0
    assert summary.total_pool == 100.0
    assert summary.remaining == 100.0


def test_borrow_recursion_is_bounded_to_one_hop(
    db: Database, event_bus: EventBus, settings_manager: SettingsManager
) -> None:
    """Borrowing propagates exactly one year forward: the prior year is summed
    with _apply_borrow_prev=False, so its own borrowed_prev is 0 and a chain of
    over-drawn years does not compound. Across three consecutive over-drawn
    years, 2026's borrowed_prev reflects ONLY 2025's (capped) overage, and
    computing every year's summary terminates without recursion errors."""
    model = VacationModel(db, event_bus)
    settings_manager.set("vacation.max_borrow_hours", 10.0)
    for year in (2024, 2025, 2026):
        model.save_settings(year, 10.0, 0.0)
        model.insert_record(
            VacationRecord(
                None, date(year, 6, 1), Hours(25.0), VacationType.ANNUAL_LEAVE
            )
        )

    summary_2026 = model.calculate_vacation_summary(2026)
    # 2025 overage = used(25) - base_pool(10) = 15, capped at max_borrow 10.
    assert summary_2026.borrowed_prev == 10.0
    # 2025 borrows from 2024 (also over-drawn) — but only one hop, so the
    # chain does not compound beyond a single year.
    assert model.calculate_vacation_summary(2025).borrowed_prev == 10.0
    # 2024's prior year (2023) is empty: overage 0 -> no borrow. The recursion
    # terminates cleanly at the unconfigured year rather than running away.
    assert model.calculate_vacation_summary(2024).borrowed_prev == 0.0
