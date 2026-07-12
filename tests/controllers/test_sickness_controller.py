import dataclasses
import sqlite3
from datetime import date

import pytest

from controllers.sickness_controller import SicknessController
from core.events import EventBus
from db.database import Database
from domain.enums import WarningCode
from domain.types import SicknessRecord
from models.sickness_model import SicknessModel


@pytest.fixture
def controller(db: Database, event_bus: EventBus) -> SicknessController:
    # Sickness controller depends on sickness model
    model = SicknessModel(db, event_bus)
    return SicknessController(model)


def test_save_valid_record(controller: SicknessController) -> None:
    rec = SicknessRecord(id=None, date=date(2026, 2, 15), hours=8.0, note="Flu")
    res = controller.save_record(rec)
    assert res.ok is True


def test_save_invalid_hours(controller: SicknessController) -> None:
    rec_low = SicknessRecord(None, date(2026, 2, 15), 0.4, "Low hours")
    assert controller.save_record(rec_low).ok is False

    rec_high = SicknessRecord(None, date(2026, 2, 15), 24.1, "High hours")
    assert controller.save_record(rec_high).ok is False


# ──────────── Defense-in-depth: SicknessRecord is frozen ────────────────────


def test_replace_into_invalid_negative_hours_raises(
    controller: SicknessController,
) -> None:
    """SicknessRecord is frozen (domain/types.py), so mutating an
    already-saved record requires dataclasses.replace(), which reruns
    __post_init__ in full — an invalid replacement raises ValueError
    immediately, rather than producing a record SicknessController
    .save_record() would need to catch as a second line of defense."""
    rec = SicknessRecord(None, date(2026, 2, 15), 8.0, "Flu")
    assert controller.save_record(rec).ok is True

    with pytest.raises(ValueError, match="Hours must be non-negative"):
        dataclasses.replace(rec, hours=-1.0)


def test_replace_into_invalid_note_too_long_raises(
    controller: SicknessController,
) -> None:
    """Same as above, but for the note-length invariant."""
    rec = SicknessRecord(None, date(2026, 2, 15), 8.0, "Flu")
    assert controller.save_record(rec).ok is True

    with pytest.raises(ValueError, match="Note is too long"):
        dataclasses.replace(rec, note="x" * 501)


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
    fetched = dataclasses.replace(fetched, hours=24.0)

    res_edit = controller.save_record(fetched)
    assert res_edit.ok is False
    assert "OVER_BALANCE_WARNING" in res_edit.errors

    res_override = controller.save_record(fetched, confirm_over_balance=True)
    assert res_override.ok is True


def test_edit_across_year_boundary_credits_correct_year(
    controller: SicknessController,
) -> None:
    # 2026 allowance = 8h, already fully used by a record we are about to edit.
    controller.model.save_settings(2026, 8.0)
    # 2027 allowance = 8h, already fully used by a different record.
    controller.model.save_settings(2027, 8.0)

    rec = SicknessRecord(None, date(2026, 12, 31), 8.0, "2026 sick day")
    assert controller.save_record(rec).ok is True

    other_2027 = SicknessRecord(None, date(2027, 1, 15), 8.0, "2027 sick day")
    assert controller.save_record(other_2027).ok is True

    # Move the 2026 record into 2027: its old hours must NOT be credited back
    # against 2027's balance (it was never counted there), so this should
    # trip the over-balance warning (8h existing + 8h moved-in > 8h allowance).
    fetched = controller.model.get_record_by_id(rec.id)
    assert fetched is not None
    fetched = dataclasses.replace(fetched, date=date(2027, 1, 20))

    res_edit = controller.save_record(fetched)
    assert res_edit.ok is False
    assert "OVER_BALANCE_WARNING" in res_edit.errors

    res_override = controller.save_record(fetched, confirm_over_balance=True)
    assert res_override.ok is True


def test_save_range_rejects_overlapping_existing_record(
    controller: SicknessController,
) -> None:
    existing = SicknessRecord(None, date(2026, 6, 10), 8.0, "Existing")
    assert controller.save_record(existing).ok is True

    res = controller.save_range(
        date(2026, 6, 8),
        date(2026, 6, 12),
        8.0,
        "Range overlaps",
    )
    assert res.ok is False
    assert "10/06/2026" in res.errors[0]

    # No extra records were inserted for the conflicting date.
    records = controller.model.get_records_in_date_range(
        date(2026, 6, 8), date(2026, 6, 12)
    )
    assert len(records) == 1


def test_save_range_rejects_note_too_long(controller: SicknessController) -> None:
    """Note-length is a context-free invariant enforced unconditionally by
    SicknessRecord.__post_init__ (domain/types.py). save_range() builds each
    SicknessRecord itself, so an over-long note raises ValueError during
    construction — this must be caught and converted to a Result rather than
    propagating, per this codebase's "controllers return Result, never raise
    for expected validation failures" convention."""
    res = controller.save_range(
        date(2026, 6, 8),
        date(2026, 6, 10),
        8.0,
        "x" * 501,
    )
    assert res.ok is False
    assert "Note is too long" in res.errors[0]

    records = controller.model.get_records_in_date_range(
        date(2026, 6, 8), date(2026, 6, 10)
    )
    assert len(records) == 0


def test_save_range_rejects_end_date_before_start_date(
    controller: SicknessController,
) -> None:
    """save_range()'s own basic-validation guard, ahead of any DB read or
    over-balance check."""
    res = controller.save_range(date(2026, 6, 10), date(2026, 6, 5), 8.0)

    assert res.ok is False
    assert res.errors == ("End date must be on or after start date.",)


@pytest.mark.parametrize(
    "hours",
    [0.0, 0.4, 24.1, 30.0],
    ids=["zero", "below-min", "above-max", "far-above-max"],
)
def test_save_range_rejects_hours_outside_valid_range(
    controller: SicknessController, hours: float
) -> None:
    """save_range()'s own 0.5-24 bound check, distinct from the identical
    bound enforced per-record by validate_sick_record() in save_record()."""
    res = controller.save_range(date(2026, 6, 8), date(2026, 6, 10), hours)

    assert res.ok is False
    assert res.errors == ("Hours must be between 0.5 and 24.",)

    records = controller.model.get_records_in_date_range(
        date(2026, 6, 8), date(2026, 6, 10)
    )
    assert len(records) == 0


# ──────────── Defense-in-depth: frozen-record bypass ────────────────────────


def test_save_record_defense_in_depth_negative_hours_via_bypass(
    controller: SicknessController,
) -> None:
    """SicknessRecord.__post_init__ makes it impossible to construct an
    invalid record through normal means, but SicknessController.save_record()
    still re-checks sickness_record_invariant_errors() as defense-in-depth
    for a record obtained by some means outside this module's control --
    simulate that with the same object.__setattr__ escape hatch
    __post_init__ itself uses (bypassing the frozen-dataclass guard) to
    force hours negative after construction."""
    rec = SicknessRecord(None, date(2026, 2, 15), 8.0, "Flu")
    object.__setattr__(rec, "hours", -1.0)

    res = controller.save_record(rec)

    assert res.ok is False
    assert "non-negative" in res.errors[0]


def test_delete_record_success(controller: SicknessController) -> None:
    """The real (non-monkeypatched) delete_record() success path: a saved
    record is actually removed and the resulting Result is ok=True."""
    rec = SicknessRecord(None, date(2026, 2, 15), 8.0, "Flu")
    assert controller.save_record(rec).ok is True
    assert rec.id is not None

    res = controller.delete_record(rec.id)

    assert res.ok is True
    assert controller.model.get_record_by_id(rec.id) is None


def test_save_range_threads_document_path(controller: SicknessController) -> None:
    res = controller.save_range(
        date(2026, 6, 8),
        date(2026, 6, 10),
        8.0,
        "Range with doc",
        document_path="/tmp/sick_note.pdf",
    )
    assert res.ok is True

    records = controller.model.get_records_in_date_range(
        date(2026, 6, 8), date(2026, 6, 10)
    )
    assert len(records) == 3
    assert all(r.document_path == "/tmp/sick_note.pdf" for r in records)


# ──────────── save_range() over-balance check (§ codebase review PR #15) ────


def test_save_range_rejects_over_balance_and_confirms_override(
    controller: SicknessController,
) -> None:
    # Allowance = 16h; a 3-day range at 8h/day would use 24h, exceeding it.
    controller.model.save_settings(2026, 16.0)

    res = controller.save_range(date(2026, 6, 1), date(2026, 6, 3), 8.0, "Sick")
    assert res.ok is False
    assert res.errors == ("OVER_BALANCE_WARNING",)

    # The rejected attempt must not have inserted any records.
    records = controller.model.get_records_in_date_range(
        date(2026, 6, 1), date(2026, 6, 3)
    )
    assert len(records) == 0

    # Re-calling with confirm_over_balance=True saves all days in the range.
    res_override = controller.save_range(
        date(2026, 6, 1), date(2026, 6, 3), 8.0, "Sick", confirm_over_balance=True
    )
    assert res_override.ok is True

    records = controller.model.get_records_in_date_range(
        date(2026, 6, 1), date(2026, 6, 3)
    )
    assert len(records) == 3


def test_save_range_year_boundary_splits_day_counts_per_year(
    controller: SicknessController,
) -> None:
    """A range spanning Dec 31 -> Jan 1 must evaluate the over-balance check
    per calendar year, not against a single year's allowance for the whole
    range. 2026 gets a generous allowance (the 1 day that falls in it is
    fine); 2027 gets a tiny allowance that the 2 days falling in it blow
    through. If save_range() incorrectly checked the whole 3-day/24h range
    against only one year's balance, this would not trip the warning."""
    controller.model.save_settings(2026, 100.0)
    controller.model.save_settings(2027, 4.0)

    res = controller.save_range(date(2026, 12, 31), date(2027, 1, 2), 8.0, "Sick")

    assert res.ok is False
    assert res.errors == ("OVER_BALANCE_WARNING",)

    records = controller.model.get_records_in_date_range(
        date(2026, 12, 31), date(2027, 1, 2)
    )
    assert len(records) == 0


def test_save_range_year_boundary_succeeds_when_both_years_have_balance(
    controller: SicknessController,
) -> None:
    """Mirror of the rejection case above, but with both years' allowances
    sufficient for the days that fall in them -- confirms the per-year split
    doesn't spuriously reject a range that fits within each year's balance,
    and that all days across the boundary are actually saved."""
    controller.model.save_settings(2026, 100.0)
    controller.model.save_settings(2027, 100.0)

    res = controller.save_range(date(2026, 12, 31), date(2027, 1, 2), 8.0, "Sick")

    assert res.ok is True

    records = controller.model.get_records_in_date_range(
        date(2026, 12, 31), date(2027, 1, 2)
    )
    assert len(records) == 3
    assert [r.date for r in records] == [
        date(2026, 12, 31),
        date(2027, 1, 1),
        date(2027, 1, 2),
    ]


# ────────────────────── Exception narrowing (§ codebase review G2 #1) ───────


def test_save_record_sqlite_error_is_caught_and_returned(
    controller: SicknessController, monkeypatch: pytest.MonkeyPatch
) -> None:
    rec = SicknessRecord(None, date(2026, 2, 15), 8.0, "Flu")

    def _boom(_record: SicknessRecord) -> int:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(controller.model, "insert_record", _boom)

    res = controller.save_record(rec)
    assert res.ok is False
    assert "Database error" in res.errors[0]


def test_save_record_non_sqlite_error_propagates(
    controller: SicknessController, monkeypatch: pytest.MonkeyPatch
) -> None:
    rec = SicknessRecord(None, date(2026, 2, 15), 8.0, "Flu")

    def _boom(_record: SicknessRecord) -> int:
        raise AttributeError("boom")

    monkeypatch.setattr(controller.model, "insert_record", _boom)

    with pytest.raises(AttributeError):
        controller.save_record(rec)


def test_delete_record_sqlite_error_is_caught_and_returned(
    controller: SicknessController, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(_record_id: int) -> None:
        raise sqlite3.Error("db error")

    monkeypatch.setattr(controller.model, "delete_record", _boom)

    res = controller.delete_record(1)
    assert res.ok is False
    assert "Database error" in res.errors[0]


def test_delete_record_non_sqlite_error_propagates(
    controller: SicknessController, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(_record_id: int) -> None:
        raise KeyError("boom")

    monkeypatch.setattr(controller.model, "delete_record", _boom)

    with pytest.raises(KeyError):
        controller.delete_record(1)


def test_save_record_update_on_since_deleted_record_returns_error_result(
    controller: SicknessController,
) -> None:
    """End-to-end exercise of the model's rowcount-based staleness check
    (not a monkeypatched generic exception): a record is saved, deleted via
    the model directly (simulating a concurrent delete from another view),
    and then re-saved through the controller's update path. update_record()
    matches zero rows, raises RecordNotFoundError, and DatabaseErrorGuard
    must convert that into an ok=False Result rather than letting it
    propagate.

    Hours stay low (8h) against the default 80h allowance so this exercises
    only the rowcount failure, not the over-balance path."""
    rec = SicknessRecord(None, date(2026, 2, 15), 8.0, "Flu")
    assert controller.save_record(rec).ok is True
    assert rec.id is not None

    controller.model.delete_record(rec.id)

    res = controller.save_record(rec)

    assert res.ok is False
    assert res.errors == (WarningCode.RECORD_NOT_FOUND.value,)


def test_save_record_update_sqlite_error_is_caught_and_returned(
    controller: SicknessController, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A genuine (non-not-found) sqlite3.Error raised by update_record() on
    the edit path must still produce the old generic "Database error: ..."
    message, not be misrouted into the RECORD_NOT_FOUND branch
    exercised by
    test_save_record_update_on_since_deleted_record_returns_error_result
    above."""
    rec = SicknessRecord(None, date(2026, 2, 15), 8.0, "Flu")
    assert controller.save_record(rec).ok is True
    assert rec.id is not None

    def _boom(_record: SicknessRecord) -> None:
        raise sqlite3.Error("db error")

    monkeypatch.setattr(controller.model, "update_record", _boom)

    edited = dataclasses.replace(rec, hours=4.0)
    res = controller.save_record(edited)

    assert res.ok is False
    assert "Database error" in res.errors[0]


def test_delete_record_on_since_deleted_record_returns_error_result(
    controller: SicknessController,
) -> None:
    """End-to-end exercise of the model's rowcount-based staleness check
    (not a monkeypatched generic exception): a record is saved, deleted once
    via the controller's own delete_record(), and then deleted again through
    the controller for the same now-stale id. The second delete_record()
    call matches zero rows, raises RecordNotFoundError, and
    DatabaseErrorGuard must convert that into an ok=False Result rather than
    letting it propagate -- mirrors
    test_save_record_update_on_since_deleted_record_returns_error_result
    above but for the delete path."""
    rec = SicknessRecord(None, date(2026, 2, 15), 8.0, "Flu")
    assert controller.save_record(rec).ok is True
    assert rec.id is not None

    assert controller.delete_record(rec.id).ok is True

    res = controller.delete_record(rec.id)

    assert res.ok is False
    assert res.errors == (WarningCode.RECORD_NOT_FOUND.value,)


def test_save_range_sqlite_error_is_caught_and_returned(
    controller: SicknessController, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(_records: list) -> None:
        raise sqlite3.Error("db error")

    monkeypatch.setattr(controller.model, "insert_records_bulk", _boom)

    res = controller.save_range(date(2026, 6, 8), date(2026, 6, 10), 8.0)
    assert res.ok is False
    assert "Database error" in res.errors[0]


def test_save_range_non_sqlite_error_propagates(
    controller: SicknessController, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(_records: list) -> None:
        raise TypeError("boom")

    monkeypatch.setattr(controller.model, "insert_records_bulk", _boom)

    with pytest.raises(TypeError):
        controller.save_range(date(2026, 6, 8), date(2026, 6, 10), 8.0)


# ──────────── Read calls inside the guard (§ codebase review gap) ───────────
# save_record()/save_range() were changed to move certain read calls inside
# the same DatabaseErrorGuard `with` block used for the write call, so that a
# sqlite3.Error raised during a read (e.g. a locked DB) also becomes a
# Result(ok=False, ...) instead of propagating. These mirror the write-call
# "sqlite_error_is_caught" tests above, but target each guarded read call.


def test_save_record_summary_read_sqlite_error_is_caught_and_returned(
    controller: SicknessController, monkeypatch: pytest.MonkeyPatch
) -> None:
    """calculate_sickness_summary() is the first read inside save_record()'s
    guard (used to compute projected_used/projected_remaining), ahead of the
    insert -- a sqlite3.Error raised there must be caught exactly like one
    raised by insert_record()."""
    rec = SicknessRecord(None, date(2026, 2, 15), 8.0, "Flu")

    def _boom(_year: int) -> None:
        raise sqlite3.Error("db error")

    monkeypatch.setattr(controller.model, "calculate_sickness_summary", _boom)

    res = controller.save_record(rec)

    assert res.ok is False
    assert "Database error" in res.errors[0]


def test_save_record_edit_lookup_read_sqlite_error_is_caught_and_returned(
    controller: SicknessController, monkeypatch: pytest.MonkeyPatch
) -> None:
    """get_record_by_id() is called inside save_record()'s guard on the edit
    path (record.id is not None) to look up the pre-edit hours for the
    projected-balance calculation -- a sqlite3.Error raised there must be
    caught the same way as one raised by insert_record()/update_record()."""
    rec = SicknessRecord(None, date(2026, 2, 15), 8.0, "Flu")
    assert controller.save_record(rec).ok is True
    assert rec.id is not None

    def _boom(_record_id: int) -> None:
        raise sqlite3.Error("db error")

    monkeypatch.setattr(controller.model, "get_record_by_id", _boom)

    edited = dataclasses.replace(rec, hours=4.0)
    res = controller.save_record(edited)

    assert res.ok is False
    assert "Database error" in res.errors[0]


def test_save_range_dates_lookup_read_sqlite_error_is_caught_and_returned(
    controller: SicknessController, monkeypatch: pytest.MonkeyPatch
) -> None:
    """get_dates_in_range() is the conflict-check read inside save_range()'s
    guard, ahead of the bulk insert -- a sqlite3.Error raised there must be
    caught the same way as one raised by insert_records_bulk()."""

    def _boom(_start: date, _end: date) -> None:
        raise sqlite3.Error("db error")

    monkeypatch.setattr(controller.model, "get_dates_in_range", _boom)

    res = controller.save_range(date(2026, 6, 8), date(2026, 6, 10), 8.0)

    assert res.ok is False
    assert "Database error" in res.errors[0]
