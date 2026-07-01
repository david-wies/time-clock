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


def test_clip_days_matches_year_clipped_summary(controller: MiliuimController) -> None:
    # Same cross-year period as test_summary_clips_to_year_boundary: the
    # per-row clip used by the tree view must agree with calculate_summary's
    # clipping, instead of returning the raw unclipped span.
    rec = MiliuimRecord(None, date(2025, 12, 28), date(2026, 1, 3))
    controller.save_record(rec)

    raw_days = (rec.end_date - rec.start_date).days + 1
    assert raw_days == 7

    assert controller.model.clip_days(rec, 2026) == 3
    assert controller.model.clip_days(rec, 2025) == 4


def test_clip_days_clips_to_month_when_given(controller: MiliuimController) -> None:
    # Period spans Jan 25 - Feb 5 2026; clipping to a specific month should
    # only count that month's overlapping days, not the whole period.
    rec = MiliuimRecord(None, date(2026, 1, 25), date(2026, 2, 5))
    controller.save_record(rec)

    assert controller.model.clip_days(rec, 2026, month=1) == 7   # Jan 25-31
    assert controller.model.clip_days(rec, 2026, month=2) == 5   # Feb 1-5
    assert controller.model.clip_days(rec, 2026, month=3) == 0   # no overlap
    assert controller.model.clip_days(rec, 2026) == 12           # whole year
