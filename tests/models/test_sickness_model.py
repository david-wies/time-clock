import pytest
from datetime import date
from domain.types import SicknessRecord
from models.sickness_model import SicknessModel
from core.events import EventBus, Event
from db.database import Database


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
    fetched.hours = 4.0
    model.update_record(fetched)
    assert change_called is True

    change_called = False
    model.delete_record(rec_id)
    assert change_called is True


def test_sickness_record_crud(db: Database, event_bus: EventBus) -> None:
    model = SicknessModel(db, event_bus)

    rec = SicknessRecord(
        id=None,
        date=date(2026, 2, 15),
        hours=8.0,
        note="Flu"
    )

    # Insert
    rec_id = model.insert_record(rec)
    assert rec_id > 0

    # Get
    fetched = model.get_record_by_id(rec_id)
    assert fetched is not None
    assert fetched.hours == 8.0
    assert fetched.note == "Flu"

    # Update
    fetched.hours = 4.0
    fetched.note = "Mild headache"
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


def test_sickness_summary_accepts_prefetched_records(db: Database, event_bus: EventBus) -> None:
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
