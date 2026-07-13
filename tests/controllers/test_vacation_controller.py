import dataclasses
import sqlite3
from datetime import date

import pytest

from controllers.vacation_controller import VacationController
from core.events import EventBus
from db.database import Database
from domain.enums import VacationType, WarningCode
from domain.types import Hours, VacationRecord
from models.time_clock_model import TimeClockModel
from models.vacation_model import VacationModel


@pytest.fixture
def controller(db: Database, event_bus: EventBus) -> VacationController:
    model = VacationModel(db, event_bus)
    return VacationController(model)


def test_save_valid_record(controller: VacationController) -> None:
    controller.model.save_settings(2026, 160.0, 40.0)
    rec = VacationRecord(
        id=None,
        date=date(2026, 7, 15),
        hours=Hours(8.0),
        vtype=VacationType.ANNUAL_LEAVE,
    )
    res = controller.save_record(rec)
    assert res.ok is True


def test_save_record_rejects_carry_over_vtype(controller: VacationController) -> None:
    """VacationRecord(vtype=CARRY_OVER, ...) is still constructible (it must
    be, so records read back from the DB via VacationModel._row_to_record()
    don't crash — see domain/types.py:VacationRecord.__post_init__ and
    tests/domain/test_types.py). This guard is what stops such a record
    (however a caller obtained one) from being routed through the general
    save path instead of add_carry_over()."""
    rec = VacationRecord(None, date(2026, 1, 1), Hours(20.0), VacationType.CARRY_OVER)
    res = controller.save_record(rec)
    assert res.ok is False
    assert "add_carry_over" in res.errors[0]


def test_save_invalid_hours(controller: VacationController) -> None:
    # Hours < 0.5
    rec_low = VacationRecord(
        None, date(2026, 7, 15), Hours(0.4), VacationType.ANNUAL_LEAVE
    )
    assert controller.save_record(rec_low).ok is False

    # Hours > 24
    rec_high = VacationRecord(
        None, date(2026, 7, 15), Hours(24.1), VacationType.ANNUAL_LEAVE
    )
    assert controller.save_record(rec_high).ok is False


# ──────────── PUBLIC_HOLIDAY's 0-hour floor exception (§ migration comment,
# db/database.py version-2 vacation_record.hours relaxation) ────────────────


def test_save_public_holiday_with_zero_hours_succeeds(
    controller: VacationController,
) -> None:
    """PUBLIC_HOLIDAY records are the one VacationType allowed to have
    hours=0 (floor of 0, instead of the usual 0.5 minimum) — this exists
    specifically to support 0-hour holiday imports (see the version-2
    migration comment in db/database.py relaxing vacation_record.hours from
    CHECK(hours > 0) to CHECK(hours >= 0))."""
    controller.model.save_settings(2026, 160.0, 40.0)
    rec = VacationRecord(
        None, date(2026, 12, 25), Hours(0.0), VacationType.PUBLIC_HOLIDAY
    )

    res = controller.save_record(rec)

    assert res.ok is True
    assert rec.id is not None


def test_save_public_holiday_over_max_hours_fails(
    controller: VacationController,
) -> None:
    """PUBLIC_HOLIDAY relaxes the *lower* bound to 0 but not the *upper*
    bound — it must still be rejected once hours exceed max_hours. max_hours
    here comes from VacationModel.get_daily_target_for_date(), which falls
    back to 8.0 when no per-weekday target has been configured (see
    models/vacation_model.py:get_daily_target_for_date), so 2026-12-25
    (a Friday, weekday()==4, with no work-day targets set in this test)
    caps at 8.0 — 10.0 hours must be rejected."""
    controller.model.save_settings(2026, 160.0, 40.0)
    rec = VacationRecord(
        None, date(2026, 12, 25), Hours(10.0), VacationType.PUBLIC_HOLIDAY
    )

    res = controller.save_record(rec)

    assert res.ok is False
    assert rec.id is None
    assert any("8.0" in e for e in res.errors)


def test_save_non_public_holiday_with_zero_hours_fails(
    controller: VacationController,
) -> None:
    """The 0-hour floor is specific to PUBLIC_HOLIDAY, not a general
    relaxation — every other VacationType still requires hours >= 0.5."""
    controller.model.save_settings(2026, 160.0, 40.0)
    rec = VacationRecord(
        None, date(2026, 12, 25), Hours(0.0), VacationType.ANNUAL_LEAVE
    )

    res = controller.save_record(rec)

    assert res.ok is False
    assert rec.id is None


# ──────────── Defense-in-depth: VacationRecord is frozen ────────────────────


def test_replace_into_invalid_negative_hours_raises(
    controller: VacationController,
) -> None:
    """VacationRecord is frozen (domain/types.py), so mutating an
    already-saved record requires dataclasses.replace(), which reruns
    __post_init__ in full — an invalid replacement raises ValueError
    immediately, rather than producing a record VacationController
    .save_record() would need to catch as a second line of defense."""
    controller.model.save_settings(2026, 160.0, 40.0)
    rec = VacationRecord(None, date(2026, 7, 15), Hours(8.0), VacationType.ANNUAL_LEAVE)
    assert controller.save_record(rec).ok is True

    with pytest.raises(ValueError, match="Hours must be non-negative"):
        dataclasses.replace(rec, hours=-1.0)


def test_replace_into_invalid_note_too_long_raises(
    controller: VacationController,
) -> None:
    """Same as above, but for the note-length invariant."""
    controller.model.save_settings(2026, 160.0, 40.0)
    rec = VacationRecord(None, date(2026, 7, 15), Hours(8.0), VacationType.ANNUAL_LEAVE)
    assert controller.save_record(rec).ok is True

    with pytest.raises(ValueError, match="Note is too long"):
        dataclasses.replace(rec, note="x" * 501)


def test_save_balance_warning_and_override(
    controller: VacationController, event_bus: EventBus
) -> None:
    # 1. Setup year settings: 16h allowance, 0h carry-over
    controller.model.save_settings(2026, 16.0, 10.0)
    # Configure daily targets high enough so hours validation does not
    # block these records
    tc_model = TimeClockModel(controller.model.db, event_bus)
    tc_model.save_work_day_targets({i: 24.0 for i in range(7)})

    # 2. Add 8h vacation (Remaining: 8h)
    rec1 = VacationRecord(
        None, date(2026, 7, 15), Hours(8.0), VacationType.ANNUAL_LEAVE
    )
    assert controller.save_record(rec1).ok is True

    # 3. Add 12h vacation -> causes balance to go to -4h. Should return warning.
    rec2 = VacationRecord(
        None, date(2026, 7, 16), Hours(12.0), VacationType.ANNUAL_LEAVE
    )
    res = controller.save_record(rec2)
    assert res.ok is False
    assert res.errors[0] == "OVER_BALANCE_WARNING"

    # 4. Save with override confirmation -> should succeed
    res_override = controller.save_record(rec2, confirm_over_balance=True)
    assert res_override.ok is True


def test_over_balance_stays_in_lockstep_with_warning_code_blocking(
    controller: VacationController,
    event_bus: EventBus,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """save_record() routes its over-balance decision through
    over_balance_decision(), so a flip of WarningCode.OVER_BALANCE.blocking is
    honored here instead of being ignored by a hardcoded ok=False. With the
    member forced non-blocking, an over-balance save must proceed (ok=True)
    without a confirm_over_balance re-call, and the OVER_BALANCE warning must
    ride along on the successful result."""
    controller.model.save_settings(2026, 16.0, 10.0)
    tc_model = TimeClockModel(controller.model.db, event_bus)
    tc_model.save_work_day_targets({i: 24.0 for i in range(7)})

    monkeypatch.setattr(WarningCode.OVER_BALANCE, "blocking", False)

    # 20h against a 16h allowance would normally block, but OVER_BALANCE is
    # now non-blocking, so the save goes through with no confirmation.
    rec = VacationRecord(
        None, date(2026, 7, 15), Hours(20.0), VacationType.ANNUAL_LEAVE
    )
    res = controller.save_record(rec)
    assert res.ok is True
    assert WarningCode.OVER_BALANCE.value in res.warnings


def test_edit_path_over_balance_warning(
    controller: VacationController, event_bus: EventBus
) -> None:
    # Setup: 16h allowance for 2026
    controller.model.save_settings(2026, 16.0, 10.0)
    # Configure daily targets high enough so hours validation does not
    # block these records
    tc_model = TimeClockModel(controller.model.db, event_bus)
    tc_model.save_work_day_targets({i: 24.0 for i in range(7)})

    # Insert first record: 8h used (8h remaining)
    rec = VacationRecord(None, date(2026, 7, 15), Hours(8.0), VacationType.ANNUAL_LEAVE)
    res = controller.save_record(rec)
    assert res.ok is True

    # Fetch and change hours to a value that exhausts the remaining balance:
    # projected_remaining = 8 (remaining) + 8 (old_hours) - 20 (new_hours)
    #                      = -4 → warning
    fetched = controller.model.get_record_by_id(rec.id)
    assert fetched is not None
    fetched = dataclasses.replace(fetched, hours=20.0)

    res_edit = controller.save_record(fetched)
    assert res_edit.ok is False
    assert "OVER_BALANCE_WARNING" in res_edit.errors

    # Confirm override succeeds
    res_override = controller.save_record(fetched, confirm_over_balance=True)
    assert res_override.ok is True


def test_save_balance_exact_zero_remaining_is_not_over_balance(
    controller: VacationController, event_bus: EventBus
) -> None:
    """Using exactly the full remaining balance (projected_remaining == 0)
    must NOT trigger OVER_BALANCE_WARNING -- the check in
    VacationController.save_record() only rejects when projected_remaining
    is strictly negative (`projected_remaining < 0`), so landing exactly on
    zero is a legitimate, fully-used balance rather than an over-balance."""
    controller.model.save_settings(2026, 16.0, 0.0)
    tc_model = TimeClockModel(controller.model.db, event_bus)
    tc_model.save_work_day_targets({i: 24.0 for i in range(7)})

    # 16h allowance, 0 carry-over -> using exactly 16h leaves remaining == 0.
    rec = VacationRecord(
        None, date(2026, 7, 15), Hours(16.0), VacationType.ANNUAL_LEAVE
    )
    res = controller.save_record(rec)

    assert res.ok is True
    assert rec.id is not None
    assert controller.model.calculate_vacation_summary(2026).remaining == 0.0


def test_edit_vtype_switch_from_debit_to_non_debit_frees_balance(
    controller: VacationController, event_bus: EventBus
) -> None:
    """Editing an existing debit record (ANNUAL_LEAVE) and switching its
    vtype to a non-debit type (UNPAID_LEAVE) must not be blocked by the
    over-balance check, even with a large hours value -- once vtype is
    non-debit, is_debit is False and the balance check is skipped entirely
    (see VacationController.save_record(): `is_debit =
    record.vtype in _DEBIT_VACATION_TYPES`)."""
    controller.model.save_settings(2026, 16.0, 0.0)
    tc_model = TimeClockModel(controller.model.db, event_bus)
    tc_model.save_work_day_targets({i: 24.0 for i in range(7)})

    # Insert a debit record using 10h of the 16h allowance (6h remaining).
    rec = VacationRecord(
        None, date(2026, 7, 15), Hours(10.0), VacationType.ANNUAL_LEAVE
    )
    assert controller.save_record(rec).ok is True

    # Edit: switch to a non-debit type with hours that would have exceeded
    # the remaining balance had it stayed a debit type (10h remaining vs.
    # 20h requested) -- should succeed since UNPAID_LEAVE never consults
    # the balance check.
    fetched = controller.model.get_record_by_id(rec.id)
    assert fetched is not None
    fetched = dataclasses.replace(fetched, vtype=VacationType.UNPAID_LEAVE, hours=20.0)

    res_edit = controller.save_record(fetched)

    assert res_edit.ok is True
    # The old debit hours are no longer counted as used, freeing the balance.
    assert controller.model.calculate_vacation_summary(2026).remaining == 16.0


def test_edit_vtype_switch_to_debit_retriggers_balance_check(
    controller: VacationController, event_bus: EventBus
) -> None:
    """Editing an existing non-debit record (UNPAID_LEAVE) and switching its
    vtype to a debit type (ANNUAL_LEAVE) must re-run the over-balance check
    against the new debit amount -- the old record's hours are never
    subtracted as `old_hours` (old_rec.vtype is not in
    _DEBIT_VACATION_TYPES), so the full new hours value is checked against
    the year's remaining allowance."""
    controller.model.save_settings(2026, 16.0, 0.0)
    tc_model = TimeClockModel(controller.model.db, event_bus)
    tc_model.save_work_day_targets({i: 24.0 for i in range(7)})

    # Insert a non-debit record; it does not touch the 16h allowance.
    rec = VacationRecord(None, date(2026, 7, 15), Hours(5.0), VacationType.UNPAID_LEAVE)
    assert controller.save_record(rec).ok is True
    assert controller.model.calculate_vacation_summary(2026).remaining == 16.0

    # Edit: switch to a debit type requesting more than the full allowance.
    fetched = controller.model.get_record_by_id(rec.id)
    assert fetched is not None
    fetched = dataclasses.replace(fetched, vtype=VacationType.ANNUAL_LEAVE, hours=20.0)

    res_edit = controller.save_record(fetched)

    assert res_edit.ok is False
    assert "OVER_BALANCE_WARNING" in res_edit.errors

    # Confirming the override still succeeds.
    res_override = controller.save_record(fetched, confirm_over_balance=True)
    assert res_override.ok is True


def test_edit_date_across_year_boundary_retriggers_balance_check(
    controller: VacationController, event_bus: EventBus
) -> None:
    """Editing an existing debit record (ANNUAL_LEAVE) and moving its `date`
    into a different year must NOT reuse the old record's hours as
    `old_hours` against the new year's balance -- old_hours belonged to the
    old year's summary, so subtracting it from the new year's
    projected_remaining would artificially inflate the apparent remaining
    balance and let an over-balance save through undetected."""
    controller.model.save_settings(2025, 16.0, 0.0)
    controller.model.save_settings(2026, 16.0, 0.0)
    tc_model = TimeClockModel(controller.model.db, event_bus)
    tc_model.save_work_day_targets({i: 24.0 for i in range(7)})

    # Insert a debit record in 2025 using nearly all of 2025's allowance.
    rec = VacationRecord(
        None, date(2025, 7, 15), Hours(15.0), VacationType.ANNUAL_LEAVE
    )
    assert controller.save_record(rec).ok is True
    assert controller.model.calculate_vacation_summary(2025).remaining == 1.0
    assert controller.model.calculate_vacation_summary(2026).remaining == 16.0

    # Edit: move the record's date into 2026 and request more hours than
    # 2026's full allowance. Without the year check, the old 2025 hours
    # (15.0) would be subtracted from 2026's projected_remaining, making the
    # over-request appear to fit.
    fetched = controller.model.get_record_by_id(rec.id)
    assert fetched is not None
    fetched = dataclasses.replace(fetched, date=date(2026, 7, 15), hours=20.0)

    res_edit = controller.save_record(fetched)

    assert res_edit.ok is False
    assert "OVER_BALANCE_WARNING" in res_edit.errors

    # Confirming the override still succeeds.
    res_override = controller.save_record(fetched, confirm_over_balance=True)
    assert res_override.ok is True


@pytest.mark.parametrize("hours", [0.0, -5.0], ids=["zero", "negative"])
def test_add_carry_over_rejects_non_positive_hours(
    controller: VacationController, hours: float
) -> None:
    """add_carry_over()'s own guard, ahead of any settings/model lookup."""
    res = controller.add_carry_over(2025, 2026, hours)

    assert res.ok is False
    assert res.errors == ("Hours to transfer must be greater than zero.",)


def test_add_carry_over_validation(controller: VacationController) -> None:
    # 1. Setup settings
    controller.model.save_settings(2025, 40.0, 10.0)  # max carryover 10h
    controller.model.save_settings(2026, 40.0, 10.0)

    # 2025 has 40h unused surplus
    allowance = controller.model.calculate_carry_over_allowance(2026)
    assert allowance.allowed_transfer == 10.0  # clamped by max_carry_over

    # 2. Try transferring 15h (Fails)
    res = controller.add_carry_over(2025, 2026, 15.0)
    assert res.ok is False
    assert "Cannot transfer" in res.errors[0]

    # 3. Try transferring 10h (Succeeds)
    res_ok = controller.add_carry_over(2025, 2026, 10.0)
    assert res_ok.ok is True


def test_save_hours_exceed_daily_target(
    controller: VacationController, event_bus: EventBus
) -> None:
    """Hours cannot exceed the daily target for that weekday."""
    tc_model = TimeClockModel(controller.model.db, event_bus)
    tc_model.save_work_day_targets(
        {0: 8.0, 1: 8.0, 2: 8.0, 3: 8.0, 4: 8.0, 5: 0.0, 6: 0.0}
    )
    controller.model.save_settings(2026, 160.0, 40.0)

    # Monday 2026-06-22, target = 8h, trying to add 10h → should fail
    rec = VacationRecord(
        None, date(2026, 6, 22), Hours(10.0), VacationType.ANNUAL_LEAVE, None
    )
    res = controller.save_record(rec)
    assert res.ok is False
    assert any("8.0" in e for e in res.errors)

    # Exactly 8h → should pass
    rec2 = VacationRecord(
        None, date(2026, 6, 22), Hours(8.0), VacationType.ANNUAL_LEAVE, None
    )
    res2 = controller.save_record(rec2)
    assert res2.ok is True


def test_save_weekend_zero_target_falls_back_to_eight_hour_cap(
    controller: VacationController, event_bus: EventBus
) -> None:
    """save_record()'s `max_hours` defaults to 8.0 whenever
    get_daily_target_for_date() returns exactly 0.0 (a configured
    weekend/day-off with no work hours) -- otherwise max_hours would stay
    0.0 and no vacation could ever be booked on a day off at all. Saturday
    2026-06-27 has target 0.0 configured below, so the cap must still allow
    up to 8.0h and reject anything over it."""
    tc_model = TimeClockModel(controller.model.db, event_bus)
    tc_model.save_work_day_targets(
        {0: 8.0, 1: 8.0, 2: 8.0, 3: 8.0, 4: 8.0, 5: 0.0, 6: 0.0}
    )
    controller.model.save_settings(2026, 160.0, 40.0)
    saturday = date(2026, 6, 27)
    assert saturday.weekday() == 5

    over_cap = VacationRecord(None, saturday, Hours(9.0), VacationType.ANNUAL_LEAVE)
    res_over = controller.save_record(over_cap)
    assert res_over.ok is False
    assert any("8.0" in e for e in res_over.errors)

    at_cap = VacationRecord(None, saturday, Hours(8.0), VacationType.ANNUAL_LEAVE)
    res_at_cap = controller.save_record(at_cap)
    assert res_at_cap.ok is True


# ──────────── Defense-in-depth: frozen-record bypass ────────────────────────


def test_save_record_defense_in_depth_negative_hours_via_bypass(
    controller: VacationController,
) -> None:
    """VacationRecord.__post_init__ makes it impossible to construct an
    invalid record through normal means, but VacationController.save_record()
    still re-checks vacation_record_invariant_errors() as defense-in-depth
    for a record obtained by some means outside this module's control --
    simulate that with the same object.__setattr__ escape hatch
    __post_init__ itself uses (bypassing the frozen-dataclass guard) to
    force hours negative after construction."""
    controller.model.save_settings(2026, 160.0, 40.0)
    rec = VacationRecord(None, date(2026, 7, 15), Hours(8.0), VacationType.ANNUAL_LEAVE)
    object.__setattr__(rec, "hours", -1.0)

    res = controller.save_record(rec)

    assert res.ok is False
    assert "non-negative" in res.errors[0]


def test_delete_record_success(controller: VacationController) -> None:
    """The real (non-monkeypatched) delete_record() success path: a saved
    record is actually removed and the resulting Result is ok=True."""
    controller.model.save_settings(2026, 160.0, 40.0)
    rec = VacationRecord(None, date(2026, 7, 15), Hours(8.0), VacationType.ANNUAL_LEAVE)
    assert controller.save_record(rec).ok is True
    assert rec.id is not None

    res = controller.delete_record(rec.id)

    assert res.ok is True
    assert controller.model.get_record_by_id(rec.id) is None


# ────────────────────── Exception narrowing (§ codebase review G2 #1) ───────


def test_save_record_sqlite_error_is_caught_and_returned(
    controller: VacationController, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller.model.save_settings(2026, 160.0, 40.0)
    rec = VacationRecord(None, date(2026, 7, 15), Hours(8.0), VacationType.ANNUAL_LEAVE)

    def _boom(_record: VacationRecord) -> int:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(controller.model, "insert_record", _boom)

    res = controller.save_record(rec)
    assert res.ok is False
    assert "Database error" in res.errors[0]


def test_save_record_non_sqlite_error_propagates(
    controller: VacationController, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller.model.save_settings(2026, 160.0, 40.0)
    rec = VacationRecord(None, date(2026, 7, 15), Hours(8.0), VacationType.ANNUAL_LEAVE)

    def _boom(_record: VacationRecord) -> int:
        raise AttributeError("boom")

    monkeypatch.setattr(controller.model, "insert_record", _boom)

    with pytest.raises(AttributeError):
        controller.save_record(rec)


def test_add_carry_over_sqlite_error_is_caught_and_returned(
    controller: VacationController, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller.model.save_settings(2025, 40.0, 10.0)
    controller.model.save_settings(2026, 40.0, 10.0)

    def _boom(_from: int, _to: int, _hours: float) -> None:
        raise sqlite3.Error("db error")

    monkeypatch.setattr(controller.model, "add_carry_over", _boom)

    res = controller.add_carry_over(2025, 2026, 5.0)
    assert res.ok is False
    assert "Database error" in res.errors[0]


def test_add_carry_over_non_sqlite_error_propagates(
    controller: VacationController, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller.model.save_settings(2025, 40.0, 10.0)
    controller.model.save_settings(2026, 40.0, 10.0)

    def _boom(_from: int, _to: int, _hours: float) -> None:
        raise TypeError("boom")

    monkeypatch.setattr(controller.model, "add_carry_over", _boom)

    with pytest.raises(TypeError):
        controller.add_carry_over(2025, 2026, 5.0)


def test_delete_record_sqlite_error_is_caught_and_returned(
    controller: VacationController, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(_record_id: int) -> None:
        raise sqlite3.Error("db error")

    monkeypatch.setattr(controller.model, "delete_record", _boom)

    res = controller.delete_record(1)
    assert res.ok is False
    assert "Database error" in res.errors[0]


def test_save_record_update_on_since_deleted_record_returns_error_result(
    controller: VacationController,
) -> None:
    """End-to-end exercise of the rowcount-based guard in
    VacationModel.update_record(): save a real record (within its year's
    allowance, so the over-balance confirm path is never triggered), delete
    it via the model directly (bypassing the controller, e.g. simulating a
    concurrent delete from another view), then try to save an edit for that
    now-stale id through the controller. update_record() raises
    RecordNotFoundError, which DatabaseErrorGuard must catch and turn into
    Result(ok=False, ...) -- not a mocked generic exception, the real
    rowcount mechanism."""
    controller.model.save_settings(2026, 160.0, 40.0)
    rec = VacationRecord(None, date(2026, 7, 15), Hours(8.0), VacationType.ANNUAL_LEAVE)
    assert controller.save_record(rec).ok is True
    assert rec.id is not None

    controller.model.delete_record(rec.id)

    stale = dataclasses.replace(rec, hours=4.0)
    res = controller.save_record(stale)

    assert res.ok is False
    assert res.errors == (WarningCode.RECORD_NOT_FOUND.value,)


def test_save_record_update_sqlite_error_is_caught_and_returned(
    controller: VacationController, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A genuine (non-not-found) sqlite3.Error raised by update_record() on
    the edit path must still produce the old generic "Database error: ..."
    message, not be misrouted into the RECORD_NOT_FOUND branch
    exercised by
    test_save_record_update_on_since_deleted_record_returns_error_result
    above."""
    controller.model.save_settings(2026, 160.0, 40.0)
    rec = VacationRecord(None, date(2026, 7, 15), Hours(8.0), VacationType.ANNUAL_LEAVE)
    assert controller.save_record(rec).ok is True
    assert rec.id is not None

    def _boom(_record: VacationRecord) -> None:
        raise sqlite3.Error("db error")

    monkeypatch.setattr(controller.model, "update_record", _boom)

    edited = dataclasses.replace(rec, hours=4.0)
    res = controller.save_record(edited)

    assert res.ok is False
    assert "Database error" in res.errors[0]


def test_delete_record_on_since_deleted_record_returns_error_result(
    controller: VacationController,
) -> None:
    """End-to-end exercise of the rowcount-based guard in
    VacationModel.delete_record(): save a real record, delete it once via
    the controller's own delete_record(), then delete the same now-stale id
    again through the controller. The second delete_record() call raises
    RecordNotFoundError on the zero-rowcount DELETE, which
    DatabaseErrorGuard must catch and turn into Result(ok=False, ...) --
    not a mocked generic exception, the real rowcount mechanism exercised by
    test_save_record_update_on_since_deleted_record_returns_error_result
    above."""
    controller.model.save_settings(2026, 160.0, 40.0)
    rec = VacationRecord(None, date(2026, 7, 15), Hours(8.0), VacationType.ANNUAL_LEAVE)
    assert controller.save_record(rec).ok is True
    assert rec.id is not None

    assert controller.delete_record(rec.id).ok is True

    res = controller.delete_record(rec.id)

    assert res.ok is False
    assert res.errors == (WarningCode.RECORD_NOT_FOUND.value,)


def test_delete_record_non_sqlite_error_propagates(
    controller: VacationController, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(_record_id: int) -> None:
        raise KeyError("boom")

    monkeypatch.setattr(controller.model, "delete_record", _boom)

    with pytest.raises(KeyError):
        controller.delete_record(1)


# ──────────── Read calls inside the guard (§ codebase review gap) ───────────
# save_record() was changed to move certain read calls inside the same
# DatabaseErrorGuard `with` block used for the write call, so that a
# sqlite3.Error raised during a read (e.g. a locked DB) also becomes a
# Result(ok=False, ...) instead of propagating. These mirror the write-call
# "sqlite_error_is_caught" tests above, but target each guarded read call.


def test_save_record_daily_target_read_sqlite_error_is_caught_and_returned(
    controller: VacationController, monkeypatch: pytest.MonkeyPatch
) -> None:
    """get_daily_target_for_date() is the first read inside save_record()'s
    guard, ahead of both the hours-bound validation and the balance check --
    a sqlite3.Error raised there must be caught exactly like one raised by
    insert_record()."""
    rec = VacationRecord(None, date(2026, 7, 15), Hours(8.0), VacationType.ANNUAL_LEAVE)

    def _boom(_d: date) -> None:
        raise sqlite3.Error("db error")

    monkeypatch.setattr(controller.model, "get_daily_target_for_date", _boom)

    res = controller.save_record(rec)

    assert res.ok is False
    assert "Database error" in res.errors[0]


def test_save_record_summary_read_sqlite_error_is_caught_and_returned(
    controller: VacationController, monkeypatch: pytest.MonkeyPatch
) -> None:
    """calculate_vacation_summary() is called inside save_record()'s guard
    for debit vtypes (ANNUAL_LEAVE/PUBLIC_HOLIDAY/SPECIAL_LEAVE) to compute
    the projected remaining balance -- a sqlite3.Error raised there must be
    caught the same way as one raised by insert_record()."""
    controller.model.save_settings(2026, 160.0, 40.0)
    rec = VacationRecord(None, date(2026, 7, 15), Hours(8.0), VacationType.ANNUAL_LEAVE)

    def _boom(_year: int) -> None:
        raise sqlite3.Error("db error")

    monkeypatch.setattr(controller.model, "calculate_vacation_summary", _boom)

    res = controller.save_record(rec)

    assert res.ok is False
    assert "Database error" in res.errors[0]


def test_save_record_edit_lookup_read_sqlite_error_is_caught_and_returned(
    controller: VacationController, monkeypatch: pytest.MonkeyPatch
) -> None:
    """get_record_by_id() is called inside save_record()'s guard on the edit
    path for debit vtypes (record.id is not None and is_debit) to look up the
    pre-edit hours for the projected-balance calculation -- a sqlite3.Error
    raised there must be caught the same way as one raised by
    insert_record()/update_record()."""
    controller.model.save_settings(2026, 160.0, 40.0)
    rec = VacationRecord(None, date(2026, 7, 15), Hours(8.0), VacationType.ANNUAL_LEAVE)
    assert controller.save_record(rec).ok is True
    assert rec.id is not None

    def _boom(_record_id: int) -> None:
        raise sqlite3.Error("db error")

    monkeypatch.setattr(controller.model, "get_record_by_id", _boom)

    edited = dataclasses.replace(rec, hours=4.0)
    res = controller.save_record(edited)

    assert res.ok is False
    assert "Database error" in res.errors[0]
