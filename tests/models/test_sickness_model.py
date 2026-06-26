import pytest
from datetime import date
from domain.types import SicknessRecord
from models.sickness_model import SicknessModel
from models.time_clock_model import TimeClockModel
from core.events import EventBus
from db.database import Database

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

def test_day_equivalent_conversion(db: Database, event_bus: EventBus) -> None:
    sick_model = SicknessModel(db, event_bus)
    tc_model = TimeClockModel(db, event_bus)

    # Setup targets: Mon(0) = 8.0h, Sat(5) = 0.0h, Wed(2) = 4.0h (half-day contract)
    targets = {0: 8.0, 5: 0.0, 2: 4.0}
    tc_model.save_work_day_targets(targets)

    # 1. Monday (target 8h): 8h sick = 1.0 day; 4h sick = 0.5 days
    mon_date = date(2026, 6, 22)  # Monday
    assert sick_model.get_day_equivalent(mon_date, 8.0) == 1.0
    assert sick_model.get_day_equivalent(mon_date, 4.0) == 0.5
    assert sick_model.get_day_equivalent(mon_date, 12.0) == 1.0  # capped at 1.0

    # 2. Wednesday (target 4h): 4h sick = 1.0 day; 2h sick = 0.5 days
    wed_date = date(2026, 6, 24)  # Wednesday
    assert sick_model.get_day_equivalent(wed_date, 4.0) == 1.0
    assert sick_model.get_day_equivalent(wed_date, 2.0) == 0.5
    assert sick_model.get_day_equivalent(wed_date, 8.0) == 1.0  # capped at 1.0

    # 3. Saturday (target 0h): capped at 1.0 day max, uses 8.0h reference
    sat_date = date(2026, 6, 27)  # Saturday
    assert sick_model.get_day_equivalent(sat_date, 8.0) == 1.0
    assert sick_model.get_day_equivalent(sat_date, 4.0) == 0.5
    assert sick_model.get_day_equivalent(sat_date, 12.0) == 1.0  # capped at 1.0

    # 4. Thursday (no target configured): falls back to 8.0h target
    thu_date = date(2026, 6, 25)  # Thursday
    assert sick_model.get_day_equivalent(thu_date, 8.0) == 1.0
    assert sick_model.get_day_equivalent(thu_date, 4.0) == 0.5

def test_sickness_summary(db: Database, event_bus: EventBus) -> None:
    sick_model = SicknessModel(db, event_bus)
    tc_model = TimeClockModel(db, event_bus)

    # 1. Save settings and targets
    sick_model.save_settings(2026, 10.0)
    tc_model.save_work_day_targets({0: 8.0, 1: 8.0, 2: 8.0, 3: 8.0, 4: 8.0, 5: 0.0, 6: 0.0})

    # 2. Add sick records (total 2 records in 2026)
    # Mon June 22: 8.0h sick (1.0 day equivalent)
    # Tue June 23: 4.0h sick (0.5 day equivalent)
    # Total: 12.0h used, 1.5 days used
    rec1 = SicknessRecord(None, date(2026, 6, 22), 8.0, "Flu")
    rec2 = SicknessRecord(None, date(2026, 6, 23), 4.0, "Cold")
    sick_model.insert_record(rec1)
    sick_model.insert_record(rec2)

    summary = sick_model.calculate_sickness_summary(2026)
    assert summary["allowance"] == 10.0
    assert summary["used_hours"] == 12.0
    assert summary["used_days"] == 1.5
    assert summary["remaining_days"] == 8.5
