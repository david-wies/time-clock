import logging
from datetime import date, time

import pytest

from core.events import Event, EventBus
from db.database import Database
from domain.enums import WorkType
from domain.types import TimeRecord
from models.time_clock_model import TimeClockModel


def test_time_record_crud(db: Database, event_bus: EventBus) -> None:
    model = TimeClockModel(db, event_bus)

    # 1. Insert
    rec = TimeRecord(
        id=None,
        date=date(2026, 6, 26),
        start_time=time(9, 0),
        end_time=time(17, 0),
        break_minutes=30,
        work_type=WorkType.REMOTE,
        office=None,
        note="Test record",
    )

    # Listen to changes
    change_called = False

    def on_change() -> None:
        nonlocal change_called
        change_called = True

    event_bus.subscribe(Event.TIME_RECORDS_CHANGED, on_change)

    rec_id = model.insert_record(rec)
    assert rec_id > 0
    assert change_called is True

    # 2. Get by ID
    fetched = model.get_record_by_id(rec_id)
    assert fetched is not None
    assert fetched.id == rec_id
    assert fetched.note == "Test record"
    assert fetched.work_type == WorkType.REMOTE

    # 3. Update
    change_called = False
    fetched.note = "Updated note"
    fetched.break_minutes = 45
    model.update_record(fetched)
    assert change_called is True

    updated = model.get_record_by_id(rec_id)
    assert updated is not None
    assert updated.note == "Updated note"
    assert updated.break_minutes == 45

    # 4. Delete
    change_called = False
    model.delete_record(rec_id)
    assert change_called is True
    assert model.get_record_by_id(rec_id) is None


def test_get_records_for_period(db: Database, event_bus: EventBus) -> None:
    model = TimeClockModel(db, event_bus)

    r1 = TimeRecord(None, date(2026, 6, 1), time(9, 0), time(17, 0), 0, WorkType.REMOTE)
    r2 = TimeRecord(
        None, date(2026, 6, 15), time(10, 0), None, 0, WorkType.REMOTE
    )  # Open record
    r3 = TimeRecord(None, date(2026, 7, 1), time(9, 0), time(17, 0), 0, WorkType.REMOTE)

    model.insert_record(r1)
    model.insert_record(r2)
    model.insert_record(r3)

    # Filter June 2026
    june_records = model.get_records_for_period(2026, month=6)
    assert len(june_records) == 2
    # Check ordering: date DESC, start_time ASC
    assert june_records[0].date == date(2026, 6, 15)
    assert june_records[1].date == date(2026, 6, 1)

    # Filter open records
    open_records = model.get_open_records()
    assert len(open_records) == 1
    assert open_records[0].date == date(2026, 6, 15)


@pytest.mark.parametrize(
    "year, month, expected_last_day",
    [
        (2024, 2, 29),  # leap-year February
        (2026, 2, 28),  # non-leap-year February
        (2026, 4, 30),  # 30-day month
    ],
)
def test_get_records_for_period_uses_real_month_end_date(
    db: Database, event_bus: EventBus, year: int, month: int, expected_last_day: int
) -> None:
    """Regression guard for the `f"{year:04d}-{month:02d}-31"` hardcoding
    bug: the query's end-of-month bound must be the real last day of the
    month (via calendar.monthrange), not a literal "-31" that happens to
    still sort correctly by lexicographic accident. Captures the actual
    bound SQLite receives via set_trace_callback (which expands bound
    parameters into the executed SQL text)."""
    model = TimeClockModel(db, event_bus)
    conn = db.get_connection()

    captured_statements: list[str] = []
    conn.set_trace_callback(captured_statements.append)
    try:
        model.get_records_for_period(year, month=month)
    finally:
        conn.set_trace_callback(None)

    select_statements = [
        s for s in captured_statements if s.startswith("SELECT * FROM time_record")
    ]
    assert len(select_statements) == 1
    expected_end_date = f"{year:04d}-{month:02d}-{expected_last_day:02d}"
    assert expected_end_date in select_statements[0]
    # A literal "-31" end bound must never appear for a month with fewer days.
    if expected_last_day != 31:
        assert f"{year:04d}-{month:02d}-31" not in select_statements[0]


def test_get_records_by_date(db: Database, event_bus: EventBus) -> None:
    model = TimeClockModel(db, event_bus)

    r1 = TimeRecord(
        None, date(2026, 6, 26), time(9, 0), time(12, 0), 0, WorkType.REMOTE
    )
    r2 = TimeRecord(None, date(2026, 6, 26), time(13, 0), time(17, 0), 0, WorkType.ROAD)
    r3 = TimeRecord(
        None, date(2026, 6, 27), time(9, 0), time(17, 0), 0, WorkType.REMOTE
    )

    model.insert_record(r1)
    model.insert_record(r2)
    model.insert_record(r3)

    june_26 = model.get_records_by_date(date(2026, 6, 26))
    assert len(june_26) == 2
    assert june_26[0].start_time == time(9, 0)
    assert june_26[1].start_time == time(13, 0)

    june_27 = model.get_records_by_date(date(2026, 6, 27))
    assert len(june_27) == 1

    assert model.get_records_by_date(date(2026, 6, 28)) == []


def test_targets_and_exceptions(db: Database, event_bus: EventBus) -> None:
    model = TimeClockModel(db, event_bus)

    # Test targets save & fetch
    targets = {0: 8.0, 1: 8.0, 4: 6.0}
    model.save_work_day_targets(targets)

    fetched_targets = model.get_work_day_targets()
    assert fetched_targets[0] == 8.0
    assert fetched_targets[4] == 6.0
    assert 2 not in fetched_targets  # Wed not saved

    # Test Exceptions save & fetch
    model.save_date_exception("2026-12-24", 4.0, "Christmas Eve")
    model.save_date_exception("2026-12-25", 0.0, "Christmas Day")

    exceptions = model.get_date_exceptions(year=2026)
    assert len(exceptions) == 2
    assert exceptions[0].date == date(2026, 12, 24)
    assert exceptions[0].hours == 4.0
    assert exceptions[1].date == date(2026, 12, 25)
    assert exceptions[1].hours == 0.0

    # Delete exception
    model.delete_date_exception_by_date("2026-12-24")
    exceptions_after = model.get_date_exceptions(year=2026)
    assert len(exceptions_after) == 1
    assert exceptions_after[0].date == date(2026, 12, 25)


def test_get_date_exceptions_skips_malformed_date_and_logs_warning(
    db: Database, event_bus: EventBus, caplog
) -> None:
    """A corrupted `date` column value (e.g. from manual DB editing) must
    not crash get_date_exceptions() — it should be logged and skipped,
    exactly like the (pre-existing) view-layer handling in
    views/time_clock_tab.py:_build_exc_dict() used to do before date
    parsing moved down into the model layer."""
    model = TimeClockModel(db, event_bus)

    model.save_date_exception("2026-12-24", 4.0, "Christmas Eve")
    conn = db.get_connection()
    try:
        with conn:
            conn.execute(
                "INSERT INTO work_day_exception (date, hours, label) "
                "VALUES ('not-a-date', 8.0, 'Corrupted row');"
            )
    finally:
        conn.close()

    with caplog.at_level(logging.WARNING, logger="models.time_clock_model"):
        exceptions = model.get_date_exceptions()

    assert len(exceptions) == 1
    assert exceptions[0].date == date(2026, 12, 24)
    assert any(
        record.levelname == "WARNING" and "malformed" in record.message.lower()
        for record in caplog.records
    )


def test_get_records_by_date_skips_malformed_row_and_logs_warning(
    db: Database, event_bus: EventBus, caplog
) -> None:
    """A row that violates a TimeRecord invariant at the DB level (e.g.
    break_minutes exceeding the shift length -- something the DB's own
    CHECK(break_minutes >= 0) constraint doesn't catch) must not crash the
    whole read. It should be logged and skipped, exactly like the
    malformed-date handling in get_date_exceptions()."""
    model = TimeClockModel(db, event_bus)

    good = TimeRecord(
        None, date(2026, 6, 26), time(9, 0), time(17, 0), 30, WorkType.REMOTE
    )
    model.insert_record(good)

    conn = db.get_connection()
    try:
        with conn:
            conn.execute(
                "INSERT INTO time_record "
                "(date, start_time, end_time, break_minutes, work_type) "
                "VALUES ('2026-06-26', '09:00', '10:00', 90, 'remote');"
            )
    finally:
        conn.close()

    with caplog.at_level(logging.WARNING, logger="models.time_clock_model"):
        records = model.get_records_by_date(date(2026, 6, 26))

    assert len(records) == 1
    assert records[0].break_minutes == 30
    assert any(
        record.levelname == "WARNING" and "malformed" in record.message.lower()
        for record in caplog.records
    )


def test_get_record_by_id_returns_none_for_malformed_row(
    db: Database, event_bus: EventBus, caplog
) -> None:
    """A single malformed row fetched by ID must return None (not raise),
    with a warning logged."""
    model = TimeClockModel(db, event_bus)

    conn = db.get_connection()
    try:
        with conn:
            cursor = conn.execute(
                "INSERT INTO time_record "
                "(date, start_time, end_time, break_minutes, work_type) "
                "VALUES ('2026-06-26', '09:00', '10:00', 90, 'remote');"
            )
            bad_id = cursor.lastrowid
    finally:
        conn.close()

    with caplog.at_level(logging.WARNING, logger="models.time_clock_model"):
        result = model.get_record_by_id(bad_id)

    assert result is None
    assert any(
        record.levelname == "WARNING" and "malformed" in record.message.lower()
        for record in caplog.records
    )
