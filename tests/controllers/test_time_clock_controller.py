import dataclasses
import logging
import sqlite3
from datetime import date, time

import pytest

from controllers.time_clock_controller import DatabaseErrorGuard, TimeClockController
from core.events import EventBus
from db.database import Database
from domain.enums import WorkType
from domain.types import TimeRecord
from models.time_clock_model import TimeClockModel
from settings import SettingsManager


@pytest.fixture
def controller(
    db: Database, event_bus: EventBus, settings_manager: SettingsManager, fixed_clock
) -> TimeClockController:
    model = TimeClockModel(db, event_bus)
    return TimeClockController(model, settings_manager, clock=fixed_clock)


def test_save_valid_record(controller: TimeClockController) -> None:
    rec = TimeRecord(
        id=None,
        date=date(2026, 6, 26),
        start_time=time(9, 0),
        end_time=time(17, 0),
        break_minutes=30,
        work_type=WorkType.REMOTE,
    )

    result = controller.save_record(rec)
    assert result.ok is True
    assert rec.id is not None


def test_save_record_with_id_updates_existing_record(
    controller: TimeClockController,
) -> None:
    """save_record() with a record.id already set must route through
    model.update_record() (the `else` branch of `if record.id is None`),
    distinct from the insert path exercised by test_save_valid_record."""
    rec = TimeRecord(
        None, date(2026, 6, 26), time(9, 0), time(17, 0), 30, WorkType.REMOTE
    )
    assert controller.save_record(rec).ok is True

    updated = dataclasses.replace(rec, break_minutes=45)
    res = controller.save_record(updated)

    assert res.ok is True
    fetched = controller.model.get_record_by_id(rec.id)
    assert fetched is not None
    assert fetched.break_minutes == 45


def test_save_overlapping_record(controller: TimeClockController) -> None:
    # Save first record: 09:00 - 17:00
    r1 = TimeRecord(
        None, date(2026, 6, 26), time(9, 0), time(17, 0), 30, WorkType.REMOTE
    )
    assert controller.save_record(r1).ok is True

    # Attempt overlap: 12:00 - 13:00
    r2 = TimeRecord(
        None, date(2026, 6, 26), time(12, 0), time(13, 0), 0, WorkType.REMOTE
    )
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
    controller: TimeClockController,
) -> None:
    """TimeRecord is frozen (domain/types.py) — direct field assignment on
    an already-saved record raises immediately, and the only way to derive
    a changed record is dataclasses.replace(), which reruns __post_init__
    in full. Either path means the value can never become invalid in the
    first place, so TimeClockController.save_record() is no longer needed
    as a second line of defense for this field."""
    rec = TimeRecord(
        None, date(2026, 6, 26), time(9, 0), time(17, 0), 30, WorkType.REMOTE
    )
    assert controller.save_record(rec).ok is True

    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.break_minutes = -1  # type: ignore[misc]

    with pytest.raises(ValueError, match="Break minutes must be non-negative"):
        dataclasses.replace(rec, break_minutes=-1)


def test_clock_out_rejects_break_exceeding_shift_length_after_mutation(
    controller: TimeClockController,
) -> None:
    """clock_out() itself fetches an open record and derives a new one with
    end_time set (via dataclasses.replace(), since TimeRecord is frozen)
    before saving. TimeRecord.__post_init__ ran successfully when the open
    record was first constructed (break_minutes was consistent with an
    end-time-less shift) but that says nothing about the shift once
    end_time is set here. clock_out() must re-run time_record_invariant_errors()
    to catch a stale break_minutes value that now exceeds the shift length —
    fixed_clock pins clock-in and clock-out at the same instant (09:00), so
    the resulting shift is zero-length and any positive break exceeds it."""
    open_rec = TimeRecord(None, date(2026, 6, 26), time(9, 0), None, 0, WorkType.REMOTE)
    record_id = controller.model.insert_record(open_rec)

    stored = controller.model.get_record_by_id(record_id)
    assert stored is not None
    stored = dataclasses.replace(stored, break_minutes=30)  # valid while still open
    controller.model.update_record(stored)

    res = controller.clock_out()

    assert res.ok is False
    assert res.errors == ("Break cannot exceed shift length.",)


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

    # 2b. force=True bypasses the OPEN_RECORD_EXISTS guard. The other open
    # record for today must be excluded from overlap validation (it has no
    # end_time, so it isn't a real conflict) — otherwise force=True could
    # never succeed while a prior open record exists.
    res_force = controller.clock_in(force=True)
    assert res_force.ok is True

    # Two open records now exist for today.
    open_recs = controller.model.get_open_records()
    assert len(open_recs) == 2

    # 3. Clock Out (Success) — ambiguous with two open records, so target
    # the second one explicitly.
    res_out = controller.clock_out(record_id=open_recs[1].id)
    assert res_out.ok is True

    # Verify one open record remains (the original clock-in).
    assert len(controller.model.get_open_records()) == 1


def test_clock_in_force_true_succeeds_with_existing_open_record(
    controller: TimeClockController,
) -> None:
    """Regression test: an open (not-yet-clocked-out) record for today must
    not be treated as an overlap conflict when clock_in(force=True) creates
    a second open record. Before the fix, clock_in() validated the new
    record against the raw list of existing records (including other open
    ones), and an open record always overlaps any new open record per
    times_overlap()'s semantics (missing end treated as end-of-day) — so
    force=True could never actually succeed while an open record existed,
    even though it correctly bypassed the OPEN_RECORD_EXISTS guard."""
    res_in = controller.clock_in()
    assert res_in.ok is True

    open_recs = controller.model.get_open_records()
    assert len(open_recs) == 1

    res_force = controller.clock_in(force=True)

    assert res_force.ok is True
    assert len(controller.model.get_open_records()) == 2


def test_save_overnight_record(controller: TimeClockController) -> None:
    rec = TimeRecord(
        None, date(2026, 6, 26), time(22, 0), time(6, 0), 0, WorkType.REMOTE
    )
    result = controller.save_record(rec)
    assert result.ok is True
    assert "OVERNIGHT_SHIFT_WARNING" in result.warnings


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


# ──────────── clock_in() work-type resolution and office defaulting ────────


def test_clock_in_with_in_site_work_type_defaults_office_from_settings(
    controller: TimeClockController,
) -> None:
    """clock_in(work_type=WorkType.IN_SITE) must default `office` from the
    live "offices" setting (first configured office) rather than leaving it
    None -- an IN_SITE TimeRecord with a blank office fails construction
    (see test_time_record_in_site_without_office_raises in
    tests/domain/test_types.py), so clock_in() would otherwise never
    succeed for IN_SITE without the caller separately passing an office."""
    res = controller.clock_in(work_type=WorkType.IN_SITE)

    assert res.ok is True
    open_recs = controller.model.get_open_records()
    assert len(open_recs) == 1
    assert open_recs[0].work_type == WorkType.IN_SITE
    # SettingsManager.DEFAULTS["offices"] == ["Office A", "Office B", "Office C"]
    assert open_recs[0].office == "Office A"


def test_clock_in_with_in_site_work_type_falls_back_to_main_office(
    controller: TimeClockController,
) -> None:
    """When the "offices" setting is explicitly configured empty (not just
    absent -- absent falls back to DEFAULTS, which is never empty), clock_in()
    must still produce a constructible IN_SITE record by falling back to the
    literal "Main Office" rather than an empty office."""
    controller.settings.set("offices", [])

    res = controller.clock_in(work_type=WorkType.IN_SITE)

    assert res.ok is True
    open_recs = controller.model.get_open_records()
    assert open_recs[0].office == "Main Office"


def test_clock_in_invalid_stored_work_type_falls_back_to_remote_with_warning(
    controller: TimeClockController, caplog: pytest.LogCaptureFixture
) -> None:
    """A corrupted/stale "last_used_work_type" setting value (e.g. from an
    older app version whose WorkType enum had different members) must not
    crash clock_in() with an unhandled ValueError from WorkType(last_wt) --
    it should log a warning and fall back to WorkType.REMOTE."""
    controller.settings.set("last_used_work_type", "not_a_real_work_type")

    with caplog.at_level(logging.WARNING):
        res = controller.clock_in()

    assert res.ok is True
    open_recs = controller.model.get_open_records()
    assert open_recs[0].work_type == WorkType.REMOTE
    assert any(
        record.levelname == "WARNING"
        and "invalid stored last_used_work_type" in record.message
        for record in caplog.records
    )


def test_clock_in_construction_error_is_caught_and_returned(
    controller: TimeClockController,
) -> None:
    """The office-defaulting logic (`office = offices[0] if offices else
    "Main Office"`) only guards against an *empty* "offices" list -- a
    non-empty list whose first entry is itself a blank string (e.g.
    "" from a bad import/edit) is still truthy, so `office` ends up "",
    and TimeRecord's IN_SITE-requires-office invariant then raises
    ValueError from inside clock_in()'s TimeRecord(...) construction. That
    must be caught and converted to a Result, not propagate."""
    controller.settings.set("offices", [""])

    res = controller.clock_in(work_type=WorkType.IN_SITE)

    assert res.ok is False
    assert "select or enter an office" in res.errors[0]
    assert controller.model.get_open_records() == []


def test_clock_in_blocking_overlap_error_is_not_swallowed(
    controller: TimeClockController,
) -> None:
    """clock_in()'s own overlap check (against closed records already on
    today's date) must surface as a blocking Result(ok=False, ...) rather
    than being silently filtered out along with OVERNIGHT_SHIFT_WARNING --
    fixed_clock pins "now" at 2026-06-26 09:00, so a pre-existing closed
    record spanning that instant (08:00-10:00) conflicts with the new open
    record clock_in() is about to create."""
    conflicting = TimeRecord(
        None, date(2026, 6, 26), time(8, 0), time(10, 0), 0, WorkType.REMOTE
    )
    controller.model.insert_record(conflicting)

    res = controller.clock_in()

    assert res.ok is False
    assert "overlaps" in res.errors[0]
    assert controller.model.get_open_records() == []


# ──────────────────────────── clock_out() error paths ──────────────────────


def test_clock_out_no_active_clock_in_found(
    controller: TimeClockController,
) -> None:
    """clock_out() with zero open records today must return a clean
    Result(ok=False, ...) rather than raising or targeting nothing."""
    res = controller.clock_out()

    assert res.ok is False
    assert res.errors == ("No active clock-in found.",)


def test_clock_out_specified_record_not_found(
    controller: TimeClockController,
) -> None:
    """An explicit record_id that doesn't match any of today's open records
    (e.g. a stale UI selection) must be rejected by name, distinctly from
    the "no open records at all" case above."""
    controller.clock_in()

    res = controller.clock_out(record_id=999999)

    assert res.ok is False
    assert res.errors == ("Specified clock-in record not found.",)
    # The real open record must be untouched.
    assert len(controller.model.get_open_records()) == 1


def test_clock_out_rejects_when_overlap_detected_at_clock_out_time(
    controller: TimeClockController,
) -> None:
    """clock_out() re-validates the closed-out record against other closed
    records on the same date -- a closed record inserted after clock-in
    (simulating a second record added in the interim) that spans the
    fixed-clock clock-out instant (09:00) must block the clock-out with a
    blocking overlap error, not silently succeed."""
    res_in = controller.clock_in()
    assert res_in.ok is True

    conflicting = TimeRecord(
        None, date(2026, 6, 26), time(8, 0), time(10, 0), 0, WorkType.REMOTE
    )
    controller.model.insert_record(conflicting)

    res_out = controller.clock_out()

    assert res_out.ok is False
    assert "overlaps" in res_out.errors[0]
    # The original record must still be open (clock-out did not persist).
    assert len(controller.model.get_open_records()) == 1


# ──────────── save_record() defense-in-depth (frozen-record bypass) ────────


def test_save_record_defense_in_depth_negative_break_via_bypass(
    controller: TimeClockController,
) -> None:
    """TimeRecord.__post_init__ makes it impossible to construct an invalid
    record through normal means, but TimeClockController.save_record()
    still re-checks time_record_invariant_errors() as defense-in-depth for
    a record obtained by some means outside this module's control --
    simulate that with the same object.__setattr__ escape hatch
    __post_init__ itself uses (bypassing the frozen-dataclass guard) to
    force break_minutes negative after construction."""
    rec = TimeRecord(
        None, date(2026, 6, 26), time(9, 0), time(17, 0), 30, WorkType.REMOTE
    )
    object.__setattr__(rec, "break_minutes", -5)

    res = controller.save_record(rec)

    assert res.ok is False
    assert "non-negative" in res.errors[0]


# ────────────── DatabaseErrorGuard misuse guard (defensive assertion) ──────


def test_database_error_guard_unwrap_without_caught_error_raises() -> None:
    """unwrap() is documented to only be called right after a `with guard:`
    block that did NOT itself return -- which only happens once a
    sqlite3.Error was caught and __exit__ populated self.result. Calling it
    on a guard whose `with` block never raised is a programming error in
    the caller, and must be reported as a clear RuntimeError rather than
    returning None or raising an opaque AttributeError."""
    guard = DatabaseErrorGuard(logging.getLogger(__name__), "unused message")

    with pytest.raises(RuntimeError, match="no error was caught"):
        guard.unwrap()


# ────────────────────── Exception narrowing (§ codebase review G2 #1) ───────


def _valid_record() -> TimeRecord:
    return TimeRecord(
        None, date(2026, 6, 26), time(9, 0), time(17, 0), 30, WorkType.REMOTE
    )


def test_save_record_sqlite_error_is_caught_and_returned(
    controller: TimeClockController, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(_record: TimeRecord) -> int:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(controller.model, "insert_record", _boom)

    res = controller.save_record(_valid_record())
    assert res.ok is False
    assert "Database error" in res.errors[0]


def test_save_record_non_sqlite_error_propagates(
    controller: TimeClockController, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(_record: TimeRecord) -> int:
        raise AttributeError("boom: a real code bug, not a DB failure")

    monkeypatch.setattr(controller.model, "insert_record", _boom)

    with pytest.raises(AttributeError):
        controller.save_record(_valid_record())


def test_save_record_swallows_settings_sqlite_error_and_logs_warning(
    controller: TimeClockController,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The record is already persisted by the time save_record() tries to
    remember last_used_work_type -- a sqlite3.Error from that best-effort
    write (time_clock_controller.py's `except sqlite3.Error` block) must not
    turn an already-successful save into a reported failure; it should log
    a warning and still return ok=True."""

    def _boom(_key: str, _value: object) -> None:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(controller.settings, "set", _boom)

    with caplog.at_level(logging.WARNING):
        res = controller.save_record(_valid_record())

    assert res.ok is True
    assert any(
        record.levelname == "WARNING"
        and "Failed to persist last_used_work_type setting" in record.message
        for record in caplog.records
    )


def test_clock_in_sqlite_error_is_caught_and_returned(
    controller: TimeClockController, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(_record: TimeRecord) -> int:
        raise sqlite3.IntegrityError("constraint failed")

    monkeypatch.setattr(controller.model, "insert_record", _boom)

    res = controller.clock_in()
    assert res.ok is False
    assert "Database error" in res.errors[0]


def test_clock_in_non_sqlite_error_propagates(
    controller: TimeClockController, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(_record: TimeRecord) -> int:
        raise TypeError("boom")

    monkeypatch.setattr(controller.model, "insert_record", _boom)

    with pytest.raises(TypeError):
        controller.clock_in()


def test_clock_out_sqlite_error_is_caught_and_returned(
    controller: TimeClockController, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller.clock_in()

    def _boom(_record: TimeRecord) -> None:
        raise sqlite3.Error("db error")

    monkeypatch.setattr(controller.model, "update_record", _boom)

    res = controller.clock_out()
    assert res.ok is False
    assert "Database error" in res.errors[0]


def test_clock_out_non_sqlite_error_propagates(
    controller: TimeClockController, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller.clock_in()

    def _boom(_record: TimeRecord) -> None:
        raise ValueError("boom")

    monkeypatch.setattr(controller.model, "update_record", _boom)

    with pytest.raises(ValueError):
        controller.clock_out()


def test_delete_record_success(controller: TimeClockController) -> None:
    """The real (non-monkeypatched) delete_record() success path: a saved
    record is actually removed and the resulting Result is ok=True."""
    rec = _valid_record()
    assert controller.save_record(rec).ok is True
    assert rec.id is not None

    res = controller.delete_record(rec.id)

    assert res.ok is True
    assert controller.model.get_record_by_id(rec.id) is None


def test_delete_record_sqlite_error_is_caught_and_returned(
    controller: TimeClockController, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(_record_id: int) -> None:
        raise sqlite3.Error("db error")

    monkeypatch.setattr(controller.model, "delete_record", _boom)

    res = controller.delete_record(1)
    assert res.ok is False
    assert "Database error" in res.errors[0]


def test_delete_record_non_sqlite_error_propagates(
    controller: TimeClockController, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(_record_id: int) -> None:
        raise KeyError("boom")

    monkeypatch.setattr(controller.model, "delete_record", _boom)

    with pytest.raises(KeyError):
        controller.delete_record(1)
