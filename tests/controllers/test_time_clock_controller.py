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


def test_save_break_exceeds_shift(controller: TimeClockController) -> None:
    # 09:00 - 10:00 (60 mins), break is 75 mins
    rec = TimeRecord(None, date(2026, 6, 26), time(
        9, 0), time(10, 0), 75, WorkType.REMOTE)
    res = controller.save_record(rec)
    assert res.ok is False
    assert "Break cannot exceed shift length" in res.errors[0]


def test_save_in_site_no_office(controller: TimeClockController) -> None:
    rec = TimeRecord(None, date(2026, 6, 26), time(
        9, 0), time(17, 0), 30, WorkType.IN_SITE, office=None)
    res = controller.save_record(rec)
    assert res.ok is False
    assert "select or enter an office" in res.errors[0]


def test_save_note_too_long(controller: TimeClockController) -> None:
    long_note = "a" * 501
    rec = TimeRecord(None, date(2026, 6, 26), time(9, 0), time(
        17, 0), 30, WorkType.REMOTE, note=long_note)
    res = controller.save_record(rec)
    assert res.ok is False
    assert "Note is too long" in res.errors[0]


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
