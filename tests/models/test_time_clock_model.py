import pytest
from datetime import date, time
from domain.types import TimeRecord
from domain.enums import WorkType
from models.time_clock_model import TimeClockModel
from core.events import EventBus, Event
from db.database import Database


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
        note="Test record"
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
    fetched.note = "Updated note"
    fetched.break_minutes = 45
    model.update_record(fetched)

    updated = model.get_record_by_id(rec_id)
    assert updated is not None
    assert updated.note == "Updated note"
    assert updated.break_minutes == 45

    # 4. Delete
    model.delete_record(rec_id)
    assert model.get_record_by_id(rec_id) is None


def test_get_records_for_period(db: Database, event_bus: EventBus) -> None:
    model = TimeClockModel(db, event_bus)

    r1 = TimeRecord(None, date(2026, 6, 1), time(
        9, 0), time(17, 0), 0, WorkType.REMOTE)
    r2 = TimeRecord(None, date(2026, 6, 15), time(10, 0),
                    None, 0, WorkType.REMOTE)  # Open record
    r3 = TimeRecord(None, date(2026, 7, 1), time(
        9, 0), time(17, 0), 0, WorkType.REMOTE)

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
    assert exceptions[0]["date"] == "2026-12-24"
    assert exceptions[0]["hours"] == 4.0
    assert exceptions[1]["date"] == "2026-12-25"
    assert exceptions[1]["hours"] == 0.0

    # Delete exception
    model.delete_date_exception_by_date("2026-12-24")
    exceptions_after = model.get_date_exceptions(year=2026)
    assert len(exceptions_after) == 1
    assert exceptions_after[0]["date"] == "2026-12-25"
