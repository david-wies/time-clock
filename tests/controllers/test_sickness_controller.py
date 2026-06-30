import pytest
from datetime import date
from domain.types import SicknessRecord
from models.sickness_model import SicknessModel
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

def test_save_balance_warning_and_override(controller: SicknessController) -> None:
    # Allowance = 16h (2 days × 8h); two records of 8h each exhaust it.
    controller.model.save_settings(2026, 16.0)

    rec1 = SicknessRecord(None, date(2026, 6, 22), 8.0, "Used 8h")
    assert controller.save_record(rec1).ok is True

    rec2 = SicknessRecord(None, date(2026, 6, 29), 8.0, "Used 8h")
    assert controller.save_record(rec2).ok is True

    # Third record pushes used to 24h, remaining to -8h
    rec3 = SicknessRecord(None, date(2026, 7, 6), 8.0, "Causes over balance")
    res = controller.save_record(rec3)
    assert res.ok is False
    assert res.errors[0] == "OVER_BALANCE_WARNING"

    # Override saves successfully
    res_override = controller.save_record(rec3, confirm_over_balance=True)
    assert res_override.ok is True


def test_edit_path_over_balance_warning(controller: SicknessController) -> None:
    # Allowance = 16h; one record of 8h leaves 8h remaining.
    controller.model.save_settings(2026, 16.0)

    rec = SicknessRecord(None, date(2026, 6, 22), 8.0, "First sick day")
    res = controller.save_record(rec)
    assert res.ok is True

    # Raise hours to 24h: projected_used = 16h - 8h + 24h = 32h → remaining = -16h
    fetched = controller.model.get_record_by_id(rec.id)
    assert fetched is not None
    fetched.hours = 24.0

    res_edit = controller.save_record(fetched)
    assert res_edit.ok is False
    assert "OVER_BALANCE_WARNING" in res_edit.errors

    res_override = controller.save_record(fetched, confirm_over_balance=True)
    assert res_override.ok is True
