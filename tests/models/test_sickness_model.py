import dataclasses
import logging
import sqlite3
from datetime import date

import pytest

from core.events import Event, EventBus
from db.database import Database
from domain.types import SicknessRecord
from models.sickness_model import SicknessModel


def test_sickness_events(db: Database, event_bus: EventBus) -> None:
    model = SicknessModel(db, event_bus)

    change_called = False

    def on_change() -> None:
        nonlocal change_called
        change_called = True

    event_bus.subscribe(Event.SICKNESS_CHANGED, on_change)

    rec = SicknessRecord(None, date(2026, 2, 15), 8.0, "Flu")
    rec_id = model.insert_record(rec)
    assert change_called is True

    change_called = False
    fetched = model.get_record_by_id(rec_id)
    assert fetched is not None
    # SicknessRecord is frozen (domain/types.py) -- dataclasses.replace()
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
    model = SicknessModel(db, event_bus)
    conn = db.get_connection()

    captured_statements: list[str] = []
    conn.set_trace_callback(captured_statements.append)
    try:
        model.get_records_for_year(year, month=month)
    finally:
        conn.set_trace_callback(None)

    select_statements = [
        s for s in captured_statements if s.startswith("SELECT * FROM sickness_record")
    ]
    assert len(select_statements) == 1
    expected_end_date = f"{year:04d}-{month:02d}-{expected_last_day:02d}"
    assert expected_end_date in select_statements[0]
    if expected_last_day != 31:
        assert f"{year:04d}-{month:02d}-31" not in select_statements[0]


def test_sickness_record_crud(db: Database, event_bus: EventBus) -> None:
    model = SicknessModel(db, event_bus)

    rec = SicknessRecord(id=None, date=date(2026, 2, 15), hours=8.0, note="Flu")

    # Insert
    rec_id = model.insert_record(rec)
    assert rec_id > 0

    # Get
    fetched = model.get_record_by_id(rec_id)
    assert fetched is not None
    assert fetched.hours == 8.0
    assert fetched.note == "Flu"

    # Update
    fetched = dataclasses.replace(fetched, hours=4.0, note="Mild headache")
    model.update_record(fetched)

    updated = model.get_record_by_id(rec_id)
    assert updated.hours == 4.0
    assert updated.note == "Mild headache"

    # Delete
    model.delete_record(rec_id)
    assert model.get_record_by_id(rec_id) is None


def test_sickness_settings(db: Database, event_bus: EventBus) -> None:
    model = SicknessModel(db, event_bus)

    model.save_settings(2026, 12.0)
    allowance = model.get_settings(2026)
    assert allowance == 12.0

    # Fallback default if not saved
    assert model.get_settings(2025) is None


def test_sickness_summary(db: Database, event_bus: EventBus) -> None:
    sick_model = SicknessModel(db, event_bus)

    # 80h allowance (10 days × 8h); records: 8h + 4h = 12h used
    sick_model.save_settings(2026, 80.0)

    rec1 = SicknessRecord(None, date(2026, 6, 22), 8.0, "Flu")
    rec2 = SicknessRecord(None, date(2026, 6, 23), 4.0, "Cold")
    sick_model.insert_record(rec1)
    sick_model.insert_record(rec2)

    summary = sick_model.calculate_sickness_summary(2026)
    assert summary.allowance_hours == 80.0
    assert summary.used_hours == 12.0
    assert summary.remaining_hours == 68.0


def test_sickness_summary_accepts_prefetched_records(
    db: Database, event_bus: EventBus
) -> None:
    """calculate_sickness_summary(year, records=...) must skip its internal
    get_records_for_year() call and use the caller-supplied list instead --
    this is what lets SicknessTab fetch year records once per refresh and
    reuse them for both the balance summary and the tree, instead of
    querying the DB twice for the same full-year record set."""
    sick_model = SicknessModel(db, event_bus)
    sick_model.save_settings(2026, 80.0)

    # Insert a record directly, then pass a *different* explicit records
    # list to prove the DB isn't re-queried -- the summary must reflect the
    # passed-in list, not what's actually in the table.
    sick_model.insert_record(SicknessRecord(None, date(2026, 6, 22), 8.0, "Flu"))

    explicit_records = [
        SicknessRecord(None, date(2026, 1, 1), 5.0, "Explicit only"),
    ]
    summary = sick_model.calculate_sickness_summary(2026, records=explicit_records)
    assert summary.used_hours == 5.0
    assert summary.remaining_hours == 75.0

    # No-arg call remains unchanged: fetches from the DB itself.
    summary_default = sick_model.calculate_sickness_summary(2026)
    assert summary_default.used_hours == 8.0


def test_get_records_for_year_skips_malformed_row_and_logs_warning(
    db: Database, event_bus: EventBus, caplog
) -> None:
    """A row that violates a SicknessRecord invariant at the DB level (e.g.
    a note longer than the domain's 500-char cap -- something no DB CHECK
    constraint enforces) must not crash the whole read. It should be logged
    and skipped, exactly like the malformed-date handling in
    TimeClockModel.get_date_exceptions()."""
    model = SicknessModel(db, event_bus)

    good = SicknessRecord(None, date(2026, 2, 15), 8.0, "ok")
    model.insert_record(good)

    conn = db.get_connection()
    try:
        with conn:
            conn.execute(
                "INSERT INTO sickness_record (date, hours, note) VALUES (?, ?, ?);",
                ("2026-02-16", 4.0, "x" * 501),
            )
    finally:
        conn.close()

    with caplog.at_level(logging.WARNING, logger="models.sickness_model"):
        records = model.get_records_for_year(2026)

    assert len(records) == 1
    assert records[0].note == "ok"
    assert model.last_skipped_count == 1
    assert any(
        record.levelname == "WARNING" and "malformed" in record.message.lower()
        for record in caplog.records
    )


def test_insert_records_bulk_empty_list_is_noop(
    db: Database, event_bus: EventBus
) -> None:
    """insert_records_bulk([]) must return immediately without opening a
    transaction or publishing SICKNESS_CHANGED -- an empty range from
    save_range() (which can't actually happen given its date-inclusive loop,
    but insert_records_bulk() is a public model method other callers could
    invoke directly with an empty list) must be a true no-op."""
    model = SicknessModel(db, event_bus)
    published = False

    def on_change() -> None:
        nonlocal published
        published = True

    event_bus.subscribe(Event.SICKNESS_CHANGED, on_change)

    model.insert_records_bulk([])

    assert published is False
    assert model.get_records_in_date_range(date(2026, 1, 1), date(2026, 12, 31)) == []


def test_update_record_without_id_raises(db: Database, event_bus: EventBus) -> None:
    """update_record() requires a persisted id -- a record that was never
    inserted (id=None) cannot be targeted by an UPDATE ... WHERE id = ?
    statement, so this is checked explicitly rather than silently updating
    zero rows."""
    model = SicknessModel(db, event_bus)
    rec = SicknessRecord(None, date(2026, 2, 15), 8.0, "Flu")

    with pytest.raises(ValueError, match="Cannot update a record without an ID"):
        model.update_record(rec)


def test_delete_record_nonexistent_id_raises_and_does_not_publish(
    db: Database, event_bus: EventBus
) -> None:
    """delete_record() must check cursor.rowcount after the DELETE, exactly
    like update_record() already does -- a DELETE against an id that was
    never inserted (or was already deleted) matches zero rows, and silently
    returning success would let a stale delete request from the UI publish
    SICKNESS_CHANGED for a mutation that never happened."""
    model = SicknessModel(db, event_bus)

    published = False

    def on_change() -> None:
        nonlocal published
        published = True

    event_bus.subscribe(Event.SICKNESS_CHANGED, on_change)

    with pytest.raises(sqlite3.DatabaseError, match="No sickness record with id=999"):
        model.delete_record(999)

    assert published is False


def test_update_record_on_since_deleted_record_raises_and_does_not_publish(
    db: Database, event_bus: EventBus
) -> None:
    """A record deleted out from under a stale in-memory reference (e.g. two
    views open on the same record, one deletes it) must not let a
    subsequent update_record() call silently no-op and report success."""
    model = SicknessModel(db, event_bus)

    rec = SicknessRecord(None, date(2026, 2, 15), 8.0, "Flu")
    rec_id = model.insert_record(rec)
    fetched = model.get_record_by_id(rec_id)
    assert fetched is not None

    model.delete_record(rec_id)

    published = False

    def on_change() -> None:
        nonlocal published
        published = True

    event_bus.subscribe(Event.SICKNESS_CHANGED, on_change)

    with pytest.raises(
        sqlite3.DatabaseError, match=f"No sickness record with id={rec_id}"
    ):
        model.update_record(fetched)

    assert published is False


def test_get_dates_in_range_skips_corrupt_date_row_and_logs_warning(
    db: Database, event_bus: EventBus, caplog
) -> None:
    """A row whose date string is not a parseable ISO date (corrupt data, a
    bad migration, a hand-edited DB) has no date to return, so it -- and
    only it -- is logged and skipped, while every other row in range must
    still come back (unlike get_records_in_date_range(), this method must
    never silently drop a row just for failing a SicknessRecord invariant,
    since SicknessController.save_range()'s conflict check needs every
    existing sick day in the range to be visible)."""
    model = SicknessModel(db, event_bus)

    good = SicknessRecord(None, date(2026, 6, 10), 8.0, "ok")
    good_id = model.insert_record(good)

    conn = db.get_connection()
    try:
        with conn:
            # "2026-06-15X" sorts lexicographically within the query's range
            # bounds but is not a parseable ISO date, so date.fromisoformat
            # raises ValueError on it.
            conn.execute(
                "INSERT INTO sickness_record (date, hours) VALUES (?, ?);",
                ("2026-06-15X", 4.0),
            )
    finally:
        conn.close()

    with caplog.at_level(logging.WARNING, logger="models.sickness_model"):
        dates = model.get_dates_in_range(date(2026, 6, 1), date(2026, 6, 30))

    assert len(dates) == 1
    assert dates[0][0] == good_id
    assert dates[0][1] == date(2026, 6, 10)
    assert any(
        record.levelname == "WARNING" and "unparseable" in record.message.lower()
        for record in caplog.records
    )


def test_get_record_by_id_returns_none_for_malformed_row(
    db: Database, event_bus: EventBus, caplog
) -> None:
    """A single malformed row fetched by ID must return None (not raise),
    with a warning logged."""
    model = SicknessModel(db, event_bus)

    conn = db.get_connection()
    try:
        with conn:
            cursor = conn.execute(
                "INSERT INTO sickness_record (date, hours, note) VALUES (?, ?, ?);",
                ("2026-02-16", 4.0, "x" * 501),
            )
            bad_id = cursor.lastrowid
    finally:
        conn.close()

    with caplog.at_level(logging.WARNING, logger="models.sickness_model"):
        result = model.get_record_by_id(bad_id)

    assert result is None
    assert any(
        record.levelname == "WARNING" and "malformed" in record.message.lower()
        for record in caplog.records
    )
