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


def test_save_single_day_period(controller: MiliuimController) -> None:
    rec = MiliuimRecord(id=None, start_date=date(
        2026, 6, 22), end_date=date(2026, 6, 22), note="Reserve duty")
    res = controller.save_record(rec)
    assert res.ok is True
    assert rec.id is not None


def test_save_multi_day_period(controller: MiliuimController) -> None:
    rec = MiliuimRecord(id=None, start_date=date(
        2026, 6, 1), end_date=date(2026, 7, 31))
    res = controller.save_record(rec)
    assert res.ok is True
    assert rec.id is not None


def test_save_end_before_start_fails(controller: MiliuimController) -> None:
    rec = MiliuimRecord(id=None, start_date=date(
        2026, 6, 22), end_date=date(2026, 6, 20))
    res = controller.save_record(rec)
    assert res.ok is False
    assert any("end date" in e.lower() for e in res.errors)


def test_save_note_too_long_fails(controller: MiliuimController) -> None:
    rec = MiliuimRecord(id=None, start_date=date(2026, 6, 1),
                        end_date=date(2026, 6, 5), note="x" * 501)
    res = controller.save_record(rec)
    assert res.ok is False


def test_delete_record(controller: MiliuimController) -> None:
    rec = MiliuimRecord(id=None, start_date=date(
        2026, 6, 22), end_date=date(2026, 6, 26))
    controller.save_record(rec)
    assert rec.id is not None
    res = controller.delete_record(rec.id)
    assert res.ok is True
    assert controller.model.get_record_by_id(rec.id) is None


def test_summary_counts_periods_and_days(controller: MiliuimController) -> None:
    controller.save_record(MiliuimRecord(
        None, date(2026, 3, 1), date(2026, 3, 10)))
    controller.save_record(MiliuimRecord(
        None, date(2026, 7, 5), date(2026, 7, 5)))
    summary = controller.model.calculate_summary(2026)
    assert summary.period_count == 2
    assert summary.total_days == 11  # 10 + 1


def test_summary_clips_to_year_boundary(controller: MiliuimController) -> None:
    # Period spans Dec 2025 → Jan 2026; only Jan 2026 days should count for 2026
    controller.save_record(MiliuimRecord(
        None, date(2025, 12, 28), date(2026, 1, 3)))
    summary = controller.model.calculate_summary(2026)
    assert summary.period_count == 1
    assert summary.total_days == 3  # Jan 1, 2, 3
