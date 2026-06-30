import pytest
from datetime import date
from domain.types import MiliuimRecord
from models.miliuim_model import MiliuimModel
from controllers.miliuim_controller import MiliuimController
from core.events import EventBus
from db.database import Database


@pytest.fixture
def controller(db: Database, event_bus: EventBus) -> MiliuimController:
    model = MiliuimModel(db, event_bus)
    return MiliuimController(model)


def test_save_valid_record(controller: MiliuimController) -> None:
    rec = MiliuimRecord(id=None, date=date(2026, 6, 22), hours=8.0, note="Reserve duty")
    res = controller.save_record(rec)
    assert res.ok is True
    assert rec.id is not None


def test_save_invalid_hours(controller: MiliuimController) -> None:
    rec = MiliuimRecord(None, date(2026, 6, 22), 0.3, None)
    assert controller.save_record(rec).ok is False

    rec2 = MiliuimRecord(None, date(2026, 6, 22), 25.0, None)
    assert controller.save_record(rec2).ok is False


def test_save_no_balance_check_when_unlimited(controller: MiliuimController) -> None:
    """When allowance_hours == 0 (unlimited), saving never triggers OVER_BALANCE_WARNING."""
    # Do not set any settings (defaults to 0 = unlimited)
    for i in range(20):
        rec = MiliuimRecord(None, date(2026, 1, i + 1), 8.0, None)
        assert controller.save_record(rec).ok is True


def test_save_range(controller: MiliuimController) -> None:
    res = controller.save_range(date(2026, 6, 22), date(2026, 6, 26), 8.0)
    assert res.ok is True
    records = controller.model.get_records_for_year(2026)
    assert len(records) == 5


def test_delete_record(controller: MiliuimController) -> None:
    rec = MiliuimRecord(None, date(2026, 6, 22), 8.0, None)
    controller.save_record(rec)
    assert rec.id is not None
    res = controller.delete_record(rec.id)
    assert res.ok is True
    assert controller.model.get_record_by_id(rec.id) is None
