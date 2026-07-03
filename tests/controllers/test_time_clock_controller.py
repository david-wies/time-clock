import sqlite3

import pytest
from datetime import date, time
from domain.types import TimeRecord
from domain.enums import WorkType
from models.time_clock_model import TimeClockModel
from controllers.time_clock_controller import TimeClockController
from settings import SettingsManager
from core.events import EventBus
from db.database import Database


@pytest.fixture
def controller(db: Database, event_bus: EventBus, settings_manager: SettingsManager, fixed_clock) -> TimeClockController:
    model = TimeClockModel(db, event_bus)
    return TimeClockController(model, settings_manager, clock=fixed_clock)


def test_save_valid_record(controller: TimeClockController) -> None:
    rec = TimeRecord(
        id=None,
        date=date(2026, 6, 26),
        start_time=time(9, 0),
        end_time=time(17, 0),
        break_minutes=30,
        work_type=WorkType.REMOTE
    )

    result = controller.save_record(rec)
    assert result.ok is True
    assert rec.id is not None


def test_save_overlapping_record(controller: TimeClockController) -> None:
    # Save first record: 09:00 - 17:00
    r1 = TimeRecord(None, date(2026, 6, 26), time(
        9, 0), time(17, 0), 30, WorkType.REMOTE)
    assert controller.save_record(r1).ok is True

    # Attempt overlap: 12:00 - 13:00
    r2 = TimeRecord(None, date(2026, 6, 26), time(
        12, 0), time(13, 0), 0, WorkType.REMOTE)
    res = controller.save_record(r2)
    assert res.ok is False
    assert "overlaps" in res.errors[0]


# NOTE: break-exceeds-shift-length, in-site-without-office, and
# note-too-long are now context-free invariants enforced unconditionally by
# TimeRecord.__post_init__ (domain/types.py) — constructing an invalid
# TimeRecord raises ValueError before controller.save_record() is ever
# reached. See tests/domain/test_types.py for that coverage
# (test_time_record_break_exceeding_shift_length_raises,
# test_time_record_in_site_without_office_raises,
# test_time_record_note_too_long_raises).


# ──────────── Defense-in-depth: mutate-then-save bypasses __post_init__ ─────

def test_save_record_rejects_negative_break_minutes_after_mutation(
        controller: TimeClockController) -> None:
    """TimeRecord.__post_init__ only runs at construction time, so
    mutating a field on an already-saved record and calling save_record()
    again must still be caught — by TimeClockController.save_record()
    re-running time_record_invariant_errors(), not by __post_init__."""
    rec = TimeRecord(None, date(2026, 6, 26), time(9, 0), time(17, 0), 30, WorkType.REMOTE)
    assert controller.save_record(rec).ok is True

    rec.break_minutes = -1
    res = controller.save_record(rec)

    assert res.ok is False
    assert res.errors == ["Break minutes must be non-negative."]


def test_clock_out_rejects_break_exceeding_shift_length_after_mutation(
        controller: TimeClockController) -> None:
    """clock_out() itself fetches an open record and mutates end_time
    in-place before saving. TimeRecord.__post_init__ ran successfully when
    the open record was first constructed (break_minutes was consistent
    with an end-time-less shift) but never re-runs once end_time is set
    here. clock_out() must re-run time_record_invariant_errors() to catch a
    stale break_minutes value that now exceeds the shift length —
    fixed_clock pins clock-in and clock-out at the same instant (09:00), so
    the resulting shift is zero-length and any positive break exceeds it."""
    open_rec = TimeRecord(None, date(2026, 6, 26), time(9, 0), None, 0, WorkType.REMOTE)
    record_id = controller.model.insert_record(open_rec)

    stored = controller.model.get_record_by_id(record_id)
    assert stored is not None
    stored.break_minutes = 30  # valid while still open (end_time is None)
    controller.model.update_record(stored)

    res = controller.clock_out()

    assert res.ok is False
    assert res.errors == ["Break cannot exceed shift length."]


def test_clock_in_out_flow(controller: TimeClockController) -> None:
    # Set default config
    controller.settings.set("last_used_work_type", "remote")

    # 1. Clock In (Success)
    res_in = controller.clock_in()
    assert res_in.ok is True

    # Verify open record exists
    open_recs = controller.model.get_open_records()
    assert len(open_recs) == 1
    assert open_recs[0].end_time is None
    assert open_recs[0].work_type == WorkType.REMOTE

    # 2. Clock In Again without force (Fails)
    res_in_again = controller.clock_in()
    assert res_in_again.ok is False
    assert res_in_again.errors[0] == "OPEN_RECORD_EXISTS"

    # 2b. force=True bypasses the OPEN_RECORD_EXISTS guard.
    # With fixed_clock at 09:00 an existing open record at 09:00 causes overlap
    # validation to fire — but the error is NOT "OPEN_RECORD_EXISTS", which
    # confirms force=True successfully bypassed that specific check.
    res_force = controller.clock_in(force=True)
    assert res_force.ok is False
    assert "OPEN_RECORD_EXISTS" not in res_force.errors
    assert "overlaps" in res_force.errors[0]

    # 3. Clock Out (Success)
    res_out = controller.clock_out()
    assert res_out.ok is True

    # Verify no open records
    assert len(controller.model.get_open_records()) == 0


def test_save_overnight_record(controller: TimeClockController) -> None:
    rec = TimeRecord(None, date(2026, 6, 26), time(
        22, 0), time(6, 0), 0, WorkType.REMOTE)
    result = controller.save_record(rec)
    assert result.ok is True
    assert "OVERNIGHT_SHIFT_WARNING" in result.errors


def test_clock_out_multiple_open_records(controller: TimeClockController) -> None:
    # Insert two open records with different start times to avoid overlap validation
    today = date(2026, 6, 26)
    r1 = TimeRecord(None, today, time(9, 0), None, 0, WorkType.REMOTE)
    r2 = TimeRecord(None, today, time(10, 0), None, 0, WorkType.ROAD)
    controller.model.insert_record(r1)
    controller.model.insert_record(r2)

    open_recs = controller.model.get_open_records()
    assert len(open_recs) == 2

    # Clock out without specifying ID should fail
    res_out = controller.clock_out()
    assert res_out.ok is False
    assert res_out.errors[0] == "MULTIPLE_OPEN_RECORDS"

    # Clock out specifying first record ID should succeed
    # Note: open_recs is sorted by start_time ASC so open_recs[0] is r1 (id 1)
    first_id = open_recs[0].id
    assert first_id is not None
    res_out_first = controller.clock_out(record_id=first_id)
    assert res_out_first.ok is True

    # Remaining open records should be 1
    assert len(controller.model.get_open_records()) == 1


# ────────────────────── Exception narrowing (§ codebase review G2 #1) ───────

def _valid_record() -> TimeRecord:
    return TimeRecord(None, date(2026, 6, 26), time(9, 0),
                       time(17, 0), 30, WorkType.REMOTE)


def test_save_record_sqlite_error_is_caught_and_returned(
        controller: TimeClockController, monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(_record: TimeRecord) -> int:
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(controller.model, "insert_record", _boom)

    res = controller.save_record(_valid_record())
    assert res.ok is False
    assert "Database error" in res.errors[0]


def test_save_record_non_sqlite_error_propagates(
        controller: TimeClockController, monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(_record: TimeRecord) -> int:
        raise AttributeError("boom: a real code bug, not a DB failure")
    monkeypatch.setattr(controller.model, "insert_record", _boom)

    with pytest.raises(AttributeError):
        controller.save_record(_valid_record())


def test_clock_in_sqlite_error_is_caught_and_returned(
        controller: TimeClockController, monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(_record: TimeRecord) -> int:
        raise sqlite3.IntegrityError("constraint failed")
    monkeypatch.setattr(controller.model, "insert_record", _boom)

    res = controller.clock_in()
    assert res.ok is False
    assert "Database error" in res.errors[0]


def test_clock_in_non_sqlite_error_propagates(
        controller: TimeClockController, monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(_record: TimeRecord) -> int:
        raise TypeError("boom")
    monkeypatch.setattr(controller.model, "insert_record", _boom)

    with pytest.raises(TypeError):
        controller.clock_in()


def test_clock_out_sqlite_error_is_caught_and_returned(
        controller: TimeClockController, monkeypatch: pytest.MonkeyPatch) -> None:
    controller.clock_in()

    def _boom(_record: TimeRecord) -> None:
        raise sqlite3.Error("db error")
    monkeypatch.setattr(controller.model, "update_record", _boom)

    res = controller.clock_out()
    assert res.ok is False
    assert "Database error" in res.errors[0]


def test_clock_out_non_sqlite_error_propagates(
        controller: TimeClockController, monkeypatch: pytest.MonkeyPatch) -> None:
    controller.clock_in()

    def _boom(_record: TimeRecord) -> None:
        raise ValueError("boom")
    monkeypatch.setattr(controller.model, "update_record", _boom)

    with pytest.raises(ValueError):
        controller.clock_out()


def test_delete_record_sqlite_error_is_caught_and_returned(
        controller: TimeClockController, monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(_record_id: int) -> None:
        raise sqlite3.Error("db error")
    monkeypatch.setattr(controller.model, "delete_record", _boom)

    res = controller.delete_record(1)
    assert res.ok is False
    assert "Database error" in res.errors[0]


def test_delete_record_non_sqlite_error_propagates(
        controller: TimeClockController, monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(_record_id: int) -> None:
        raise KeyError("boom")
    monkeypatch.setattr(controller.model, "delete_record", _boom)

    with pytest.raises(KeyError):
        controller.delete_record(1)
