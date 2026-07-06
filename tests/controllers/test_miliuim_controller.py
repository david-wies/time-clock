import sqlite3
from datetime import date

import pytest

from controllers.miliuim_controller import MiliuimController
from core.events import EventBus
from db.database import Database
from domain.types import MiliuimRecord
from models.miliuim_model import MiliuimModel


@pytest.fixture
def controller(db: Database, event_bus: EventBus) -> MiliuimController:
    model = MiliuimModel(db, event_bus)
    return MiliuimController(model)


def test_save_single_day_period(controller: MiliuimController) -> None:
    rec = MiliuimRecord(
        id=None,
        start_date=date(2026, 6, 22),
        end_date=date(2026, 6, 22),
        note="Reserve duty",
    )
    res = controller.save_record(rec)
    assert res.ok is True
    assert rec.id is not None


def test_save_multi_day_period(controller: MiliuimController) -> None:
    rec = MiliuimRecord(
        id=None, start_date=date(2026, 6, 1), end_date=date(2026, 7, 31)
    )
    res = controller.save_record(rec)
    assert res.ok is True
    assert rec.id is not None


# NOTE: end-before-start and note-too-long are now context-free invariants
# enforced unconditionally by MiliuimRecord.__post_init__
# (domain/types.py) — constructing an invalid MiliuimRecord raises
# ValueError before controller.save_record() is ever reached. See
# tests/domain/test_types.py for that coverage
# (test_miliuim_record_end_before_start_raises,
# test_miliuim_record_note_too_long_raises).


def test_delete_record(controller: MiliuimController) -> None:
    rec = MiliuimRecord(
        id=None, start_date=date(2026, 6, 22), end_date=date(2026, 6, 26)
    )
    controller.save_record(rec)
    assert rec.id is not None
    res = controller.delete_record(rec.id)
    assert res.ok is True
    assert controller.model.get_record_by_id(rec.id) is None


def test_summary_counts_periods_and_days(controller: MiliuimController) -> None:
    controller.save_record(MiliuimRecord(None, date(2026, 3, 1), date(2026, 3, 10)))
    controller.save_record(MiliuimRecord(None, date(2026, 7, 5), date(2026, 7, 5)))
    summary = controller.model.calculate_summary(2026)
    assert summary.period_count == 2
    assert summary.total_days == 11  # 10 + 1


def test_summary_clips_to_year_boundary(controller: MiliuimController) -> None:
    # Period spans Dec 2025 → Jan 2026; only Jan 2026 days should count for 2026
    controller.save_record(MiliuimRecord(None, date(2025, 12, 28), date(2026, 1, 3)))
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

    assert controller.model.clip_days(rec, 2026, month=1) == 7  # Jan 25-31
    assert controller.model.clip_days(rec, 2026, month=2) == 5  # Feb 1-5
    assert controller.model.clip_days(rec, 2026, month=3) == 0  # no overlap
    assert controller.model.clip_days(rec, 2026) == 12  # whole year


# ─────────────────────────── Overlap validation ─────────────────────────────


def test_save_overlapping_period_rejected(controller: MiliuimController) -> None:
    controller.save_record(MiliuimRecord(None, date(2026, 6, 1), date(2026, 6, 10)))

    overlapping = MiliuimRecord(None, date(2026, 6, 5), date(2026, 6, 15))
    res = controller.save_record(overlapping)

    assert res.ok is False
    assert any("overlap" in e.lower() for e in res.errors)
    assert overlapping.id is None


def test_save_non_overlapping_period_accepted(controller: MiliuimController) -> None:
    controller.save_record(MiliuimRecord(None, date(2026, 6, 1), date(2026, 6, 10)))

    non_overlapping = MiliuimRecord(None, date(2026, 7, 1), date(2026, 7, 10))
    res = controller.save_record(non_overlapping)

    assert res.ok is True
    assert non_overlapping.id is not None


def test_save_back_to_back_periods_accepted(controller: MiliuimController) -> None:
    """Boundary case: one period ends the day before the next starts.

    Not an overlap.
    """
    controller.save_record(MiliuimRecord(None, date(2026, 6, 1), date(2026, 6, 10)))

    back_to_back = MiliuimRecord(None, date(2026, 6, 11), date(2026, 6, 20))
    res = controller.save_record(back_to_back)

    assert res.ok is True
    assert back_to_back.id is not None


def test_save_period_sharing_boundary_day_rejected(
    controller: MiliuimController,
) -> None:
    """Boundary case: new period starts on the same day the existing one ends —
    that day would be double-counted, so it must be rejected as an overlap."""
    controller.save_record(MiliuimRecord(None, date(2026, 6, 1), date(2026, 6, 10)))

    shares_boundary = MiliuimRecord(None, date(2026, 6, 10), date(2026, 6, 20))
    res = controller.save_record(shares_boundary)

    assert res.ok is False
    assert any("overlap" in e.lower() for e in res.errors)


def test_editing_record_does_not_overlap_with_itself(
    controller: MiliuimController,
) -> None:
    """Saving (updating) an existing record must not flag it as overlapping itself."""
    rec = MiliuimRecord(None, date(2026, 6, 1), date(2026, 6, 10))
    controller.save_record(rec)
    assert rec.id is not None

    rec.note = "updated"
    res = controller.save_record(rec)

    assert res.ok is True


def test_editing_record_into_overlap_with_another_rejected(
    controller: MiliuimController,
) -> None:
    controller.save_record(MiliuimRecord(None, date(2026, 1, 1), date(2026, 1, 10)))
    other = MiliuimRecord(None, date(2026, 3, 1), date(2026, 3, 10))
    controller.save_record(other)
    assert other.id is not None

    other.start_date = date(2026, 1, 5)
    other.end_date = date(2026, 1, 15)
    res = controller.save_record(other)

    assert res.ok is False
    assert any("overlap" in e.lower() for e in res.errors)


# ──────────── Defense-in-depth: mutate-then-save bypasses __post_init__ ─────


def test_save_record_rejects_end_before_start_after_mutation(
    controller: MiliuimController,
) -> None:
    """MiliuimRecord.__post_init__ only runs at construction time, so
    mutating a field on an already-saved record and calling save_record()
    again must still be caught — by MiliuimController.save_record()
    re-running miliuim_record_invariant_errors(), not by __post_init__."""
    rec = MiliuimRecord(None, date(2026, 6, 1), date(2026, 6, 10))
    assert controller.save_record(rec).ok is True

    rec.end_date = date(2026, 5, 20)  # now before start_date
    res = controller.save_record(rec)

    assert res.ok is False
    assert res.errors == ["End date must be on or after start date."]


def test_save_record_rejects_note_too_long_after_mutation(
    controller: MiliuimController,
) -> None:
    """MiliuimRecord.note is a _ValidatingRecord-validated field (domain/
    types.py), so mutating it to an invalid value on an already-saved
    record now raises ValueError immediately — the value can never become
    invalid in the first place, so MiliuimController.save_record() is no
    longer needed as a second line of defense for this field."""
    rec = MiliuimRecord(None, date(2026, 6, 1), date(2026, 6, 10))
    assert controller.save_record(rec).ok is True

    with pytest.raises(ValueError, match="Note is too long"):
        rec.note = "x" * 501


# ────────────────────── Exception narrowing (§ codebase review G2 #1) ───────


def test_save_record_sqlite_error_is_caught_and_returned(
    controller: MiliuimController, monkeypatch: pytest.MonkeyPatch
) -> None:
    rec = MiliuimRecord(None, date(2026, 6, 22), date(2026, 6, 22))

    def _boom(_record: MiliuimRecord) -> int:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(controller.model, "insert_record", _boom)

    res = controller.save_record(rec)
    assert res.ok is False
    assert "Database error" in res.errors[0]


def test_save_record_non_sqlite_error_propagates(
    controller: MiliuimController, monkeypatch: pytest.MonkeyPatch
) -> None:
    rec = MiliuimRecord(None, date(2026, 6, 22), date(2026, 6, 22))

    def _boom(_record: MiliuimRecord) -> int:
        raise AttributeError("boom")

    monkeypatch.setattr(controller.model, "insert_record", _boom)

    with pytest.raises(AttributeError):
        controller.save_record(rec)


def test_delete_record_sqlite_error_is_caught_and_returned(
    controller: MiliuimController, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(_record_id: int) -> None:
        raise sqlite3.Error("db error")

    monkeypatch.setattr(controller.model, "delete_record", _boom)

    res = controller.delete_record(1)
    assert res.ok is False
    assert "Database error" in res.errors[0]


def test_delete_record_non_sqlite_error_propagates(
    controller: MiliuimController, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(_record_id: int) -> None:
        raise KeyError("boom")

    monkeypatch.setattr(controller.model, "delete_record", _boom)

    with pytest.raises(KeyError):
        controller.delete_record(1)
