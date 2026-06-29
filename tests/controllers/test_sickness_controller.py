import pytest
from datetime import date
from domain.types import SicknessRecord
from models.sickness_model import SicknessModel
from models.time_clock_model import TimeClockModel
from controllers.sickness_controller import SicknessController
from core.events import EventBus
from db.database import Database

@pytest.fixture
def controller(db: Database, event_bus: EventBus) -> SicknessController:
    # Sickness controller depends on sickness model
    model = SicknessModel(db, event_bus)
    return SicknessController(model)

def test_save_valid_record(controller: SicknessController) -> None:
    rec = SicknessRecord(
        id=None,
        date=date(2026, 2, 15),
        hours=8.0,
        note="Flu"
    )
    res = controller.save_record(rec)
    assert res.ok is True

def test_save_invalid_hours(controller: SicknessController) -> None:
    rec_low = SicknessRecord(None, date(2026, 2, 15), 0.4, "Low hours")
    assert controller.save_record(rec_low).ok is False

    rec_high = SicknessRecord(None, date(2026, 2, 15), 24.1, "High hours")
    assert controller.save_record(rec_high).ok is False

def test_save_balance_warning_and_override(controller: SicknessController, event_bus: EventBus) -> None:
    # 1. Setup settings & daily targets
    # 10 days allowance. Monday target is 8.0h (1 day)
    controller.model.save_settings(2026, 2.0)  # low allowance: 2 days

    tc_model = TimeClockModel(controller.model.db, event_bus)
    tc_model.save_work_day_targets({0: 8.0, 1: 8.0, 2: 8.0, 3: 8.0, 4: 8.0, 5: 0.0, 6: 0.0})

    # Monday June 22 (Mon = 0, target 8.0h = 1 day)
    # Monday June 29 (Mon = 0, target 8.0h = 1 day)
    # Total sick used = 2 days

    rec1 = SicknessRecord(None, date(2026, 6, 22), 8.0, "Used 1 day")
    assert controller.save_record(rec1).ok is True

    rec2 = SicknessRecord(None, date(2026, 6, 29), 8.0, "Used 1 day")
    assert controller.save_record(rec2).ok is True

    # 3. Add third record (causes -1 day remaining)
    rec3 = SicknessRecord(None, date(2026, 7, 6), 8.0, "Causes over balance")
    res = controller.save_record(rec3)
    assert res.ok is False
    assert res.errors[0] == "OVER_BALANCE_WARNING"

    # 4. Override
    res_override = controller.save_record(rec3, confirm_over_balance=True)
    assert res_override.ok is True


def test_edit_path_over_balance_warning(controller: SicknessController, event_bus: EventBus) -> None:
    # Setup: allowance = 2 days; Monday target = 8h (= 1 day)
    controller.model.save_settings(2026, 2.0)
    tc_model = TimeClockModel(controller.model.db, event_bus)
    tc_model.save_work_day_targets(
        {0: 8.0, 1: 8.0, 2: 8.0, 3: 8.0, 4: 8.0, 5: 0.0, 6: 0.0})

    # Insert one record: Monday 8h (= 1 day used, 1 day remaining)
    mon_date = date(2026, 6, 22)  # Monday
    rec = SicknessRecord(None, mon_date, 8.0, "First sick day")
    res = controller.save_record(rec)
    assert res.ok is True

    # Fetch and raise hours to 24h (= 3 day equiv on Monday)
    # projected_used_days = 1.0 - 1.0 + 3.0 = 3.0 → projected_remaining = 2.0 - 3.0 = -1.0
    fetched = controller.model.get_record_by_id(rec.id)
    assert fetched is not None
    fetched.hours = 24.0

    res_edit = controller.save_record(fetched)
    assert res_edit.ok is False
    assert "OVER_BALANCE_WARNING" in res_edit.errors

    # Confirm override succeeds
    res_override = controller.save_record(fetched, confirm_over_balance=True)
    assert res_override.ok is True
