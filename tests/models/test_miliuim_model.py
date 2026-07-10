import dataclasses
import logging
import sqlite3
from datetime import date

import pytest

from core.events import Event, EventBus
from db.database import Database
from domain.types import MiliuimRecord
from models.miliuim_model import MiliuimModel


def test_miliuim_events(db: Database, event_bus: EventBus) -> None:
    model = MiliuimModel(db, event_bus)

    change_called = False

    def on_change() -> None:
        nonlocal change_called
        change_called = True

    event_bus.subscribe(Event.MILIUIM_CHANGED, on_change)

    rec = MiliuimRecord(None, date(2026, 2, 15), date(2026, 2, 20), "Reserve duty")
    rec_id = model.insert_record(rec)
    assert change_called is True

    change_called = False
    fetched = model.get_record_by_id(rec_id)
    assert fetched is not None
    # MiliuimRecord is frozen (domain/types.py) -- dataclasses.replace()
    # builds a new, revalidated instance instead of mutating in place.
    fetched = dataclasses.replace(fetched, note="Updated note")
    model.update_record(fetched)
    assert change_called is True

    change_called = False
    model.delete_record(rec_id)
    assert change_called is True


def test_miliuim_record_crud(db: Database, event_bus: EventBus) -> None:
    model = MiliuimModel(db, event_bus)

    rec = MiliuimRecord(
        id=None,
        start_date=date(2026, 2, 15),
        end_date=date(2026, 2, 20),
        note="Reserve duty",
        document_path="/docs/call_up.pdf",
    )

    # Insert
    rec_id = model.insert_record(rec)
    assert rec_id > 0

    # Get
    fetched = model.get_record_by_id(rec_id)
    assert fetched is not None
    assert fetched.start_date == date(2026, 2, 15)
    assert fetched.end_date == date(2026, 2, 20)
    assert fetched.note == "Reserve duty"
    assert fetched.document_path == "/docs/call_up.pdf"

    # Update
    fetched = dataclasses.replace(fetched, end_date=date(2026, 2, 25), note="Extended")
    model.update_record(fetched)

    updated = model.get_record_by_id(rec_id)
    assert updated is not None
    assert updated.end_date == date(2026, 2, 25)
    assert updated.note == "Extended"

    # Delete
    model.delete_record(rec_id)
    assert model.get_record_by_id(rec_id) is None


def test_update_record_without_id_raises(db: Database, event_bus: EventBus) -> None:
    """update_record() requires a persisted id -- a record that was never
    inserted (id=None) cannot be targeted by an UPDATE ... WHERE id = ?
    statement, so this is checked explicitly rather than silently updating
    zero rows."""
    model = MiliuimModel(db, event_bus)
    rec = MiliuimRecord(None, date(2026, 6, 1), date(2026, 6, 10))

    with pytest.raises(ValueError, match="Cannot update a record without an ID"):
        model.update_record(rec)


def test_delete_record_nonexistent_id_raises(db: Database, event_bus: EventBus) -> None:
    """delete_record() must check cursor.rowcount, mirroring
    update_record() above -- otherwise deleting an id that doesn't exist (or
    was already deleted) silently succeeds and still publishes
    MILIUIM_CHANGED, even though nothing was actually deleted."""
    model = MiliuimModel(db, event_bus)

    change_called = False

    def on_change() -> None:
        nonlocal change_called
        change_called = True

    event_bus.subscribe(Event.MILIUIM_CHANGED, on_change)

    with pytest.raises(
        sqlite3.DatabaseError, match="No Miliuim record with id=999 exists to delete"
    ):
        model.delete_record(999)

    assert change_called is False


def test_update_record_on_since_deleted_record_raises(
    db: Database, event_bus: EventBus
) -> None:
    """A record fetched/held before another caller (or the same one) deletes
    it becomes stale -- update_record() must reject it via the
    cursor.rowcount == 0 check rather than silently doing nothing."""
    model = MiliuimModel(db, event_bus)

    rec = MiliuimRecord(None, date(2026, 4, 1), date(2026, 4, 5))
    rec_id = model.insert_record(rec)
    fetched = model.get_record_by_id(rec_id)
    assert fetched is not None

    model.delete_record(rec_id)

    change_called = False

    def on_change() -> None:
        nonlocal change_called
        change_called = True

    event_bus.subscribe(Event.MILIUIM_CHANGED, on_change)

    stale = dataclasses.replace(fetched, note="too late")
    with pytest.raises(
        sqlite3.DatabaseError,
        match=f"No Miliuim record with id={rec_id} exists to update",
    ):
        model.update_record(stale)

    assert change_called is False


def test_get_records_for_year_without_month_filter(
    db: Database, event_bus: EventBus
) -> None:
    model = MiliuimModel(db, event_bus)

    rec_jan = MiliuimRecord(None, date(2026, 1, 5), date(2026, 1, 10))
    rec_dec = MiliuimRecord(None, date(2026, 12, 1), date(2026, 12, 5))
    rec_other_year = MiliuimRecord(None, date(2025, 6, 1), date(2025, 6, 5))
    model.insert_record(rec_jan)
    model.insert_record(rec_dec)
    model.insert_record(rec_other_year)

    records = model.get_records_for_year(2026)

    assert len(records) == 2
    starts = {r.start_date for r in records}
    assert starts == {date(2026, 1, 5), date(2026, 12, 1)}
    # Ordered by start_date DESC.
    assert records[0].start_date == date(2026, 12, 1)
    assert records[1].start_date == date(2026, 1, 5)


def test_get_records_for_year_with_month_filter(
    db: Database, event_bus: EventBus
) -> None:
    model = MiliuimModel(db, event_bus)

    rec_feb = MiliuimRecord(None, date(2026, 2, 10), date(2026, 2, 15))
    rec_march = MiliuimRecord(None, date(2026, 3, 1), date(2026, 3, 5))
    model.insert_record(rec_feb)
    model.insert_record(rec_march)

    records = model.get_records_for_year(2026, month=2)

    assert len(records) == 1
    assert records[0].start_date == date(2026, 2, 10)


def test_get_records_in_date_range(db: Database, event_bus: EventBus) -> None:
    model = MiliuimModel(db, event_bus)

    rec_inside = MiliuimRecord(None, date(2026, 6, 10), date(2026, 6, 15))
    rec_overlap_start = MiliuimRecord(None, date(2026, 5, 28), date(2026, 6, 2))
    rec_outside = MiliuimRecord(None, date(2026, 8, 1), date(2026, 8, 5))
    model.insert_record(rec_inside)
    model.insert_record(rec_overlap_start)
    model.insert_record(rec_outside)

    records = model.get_records_in_date_range(date(2026, 6, 1), date(2026, 6, 30))

    assert len(records) == 2
    # Ordered by start_date ASC.
    assert records[0].start_date == date(2026, 5, 28)
    assert records[1].start_date == date(2026, 6, 10)


def test_get_records_for_year_skips_malformed_row_and_logs_warning(
    db: Database, event_bus: EventBus, caplog
) -> None:
    """A row that violates a MiliuimRecord invariant at the DB level (e.g. a
    note longer than the domain's 500-char cap -- something no DB CHECK
    constraint enforces) must not crash the whole read. It should be logged
    and skipped, exactly like the equivalent SicknessModel behavior."""
    model = MiliuimModel(db, event_bus)

    good = MiliuimRecord(None, date(2026, 2, 15), date(2026, 2, 20), "ok")
    model.insert_record(good)

    conn = db.get_connection()
    try:
        with conn:
            conn.execute(
                "INSERT INTO miliuim_period (start_date, end_date, note)"
                " VALUES (?, ?, ?);",
                ("2026-03-01", "2026-03-05", "x" * 501),
            )
    finally:
        conn.close()

    with caplog.at_level(logging.WARNING, logger="models.miliuim_model"):
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
    model = MiliuimModel(db, event_bus)

    conn = db.get_connection()
    try:
        with conn:
            cursor = conn.execute(
                "INSERT INTO miliuim_period (start_date, end_date, note)"
                " VALUES (?, ?, ?);",
                ("2026-03-01", "2026-03-05", "x" * 501),
            )
            bad_id = cursor.lastrowid
    finally:
        conn.close()

    with caplog.at_level(logging.WARNING, logger="models.miliuim_model"):
        result = model.get_record_by_id(bad_id)

    assert result is None
    assert any(
        record.levelname == "WARNING" and "malformed" in record.message.lower()
        for record in caplog.records
    )


def test_get_date_ranges_in_range_skips_corrupt_date_row_and_logs_warning(
    db: Database, event_bus: EventBus, caplog
) -> None:
    """A row whose start_date/end_date string is not a parseable ISO date
    (corrupt data, a bad migration, a hand-edited DB) has no date to compare
    for overlap, so it -- and only it -- is logged and skipped, while every
    other overlapping row must still come back (unlike
    get_records_in_date_range(), this method must never silently drop a row
    just for failing a MiliuimRecord invariant)."""
    model = MiliuimModel(db, event_bus)

    good = MiliuimRecord(None, date(2026, 6, 10), date(2026, 6, 15))
    good_id = model.insert_record(good)

    conn = db.get_connection()
    try:
        with conn:
            # "2026-06-15X" sorts lexicographically within the query's range
            # bounds (and satisfies the end_date >= start_date CHECK, since
            # both columns hold the identical string) but is not a parseable
            # ISO date, so date.fromisoformat raises ValueError on it.
            conn.execute(
                "INSERT INTO miliuim_period (start_date, end_date) VALUES (?, ?);",
                ("2026-06-15X", "2026-06-15X"),
            )
    finally:
        conn.close()

    with caplog.at_level(logging.WARNING, logger="models.miliuim_model"):
        ranges = model.get_date_ranges_in_range(date(2026, 6, 1), date(2026, 6, 30))

    assert len(ranges) == 1
    assert ranges[0][0] == good_id
    assert ranges[0][1] == date(2026, 6, 10)
    assert ranges[0][2] == date(2026, 6, 15)
    assert any(
        record.levelname == "WARNING" and "unparseable" in record.message.lower()
        for record in caplog.records
    )
