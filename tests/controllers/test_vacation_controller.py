import pytest
from datetime import date
from domain.types import VacationRecord
from domain.enums import VacationType
from models.vacation_model import VacationModel
from controllers.vacation_controller import VacationController
from core.events import EventBus
from db.database import Database


@pytest.fixture
def controller(db: Database, event_bus: EventBus) -> VacationController:
    model = VacationModel(db, event_bus)
    return VacationController(model)


def test_save_valid_record(controller: VacationController) -> None:
    controller.model.save_settings(2026, 160.0, 40.0)
    rec = VacationRecord(
        id=None,
        date=date(2026, 7, 15),
        hours=8.0,
        vtype=VacationType.ANNUAL_LEAVE
    )
    res = controller.save_record(rec)
    assert res.ok is True


def test_save_invalid_hours(controller: VacationController) -> None:
    # Hours < 0.5
    rec_low = VacationRecord(None, date(2026, 7, 15),
                             0.4, VacationType.ANNUAL_LEAVE)
    assert controller.save_record(rec_low).ok is False

    # Hours > 24
    rec_high = VacationRecord(None, date(2026, 7, 15),
                              24.1, VacationType.ANNUAL_LEAVE)
    assert controller.save_record(rec_high).ok is False


def test_save_balance_warning_and_override(controller: VacationController) -> None:
    # 1. Setup year settings: 16h allowance, 0h carry-over
    controller.model.save_settings(2026, 16.0, 10.0)

    # 2. Add 8h vacation (Remaining: 8h)
    rec1 = VacationRecord(None, date(2026, 7, 15), 8.0,
                          VacationType.ANNUAL_LEAVE)
    assert controller.save_record(rec1).ok is True

    # 3. Add 12h vacation -> causes balance to go to -4h. Should return warning.
    rec2 = VacationRecord(None, date(2026, 7, 16), 12.0,
                          VacationType.ANNUAL_LEAVE)
    res = controller.save_record(rec2)
    assert res.ok is False
    assert res.errors[0] == "OVER_BALANCE_WARNING"

    # 4. Save with override confirmation -> should succeed
    res_override = controller.save_record(rec2, confirm_over_balance=True)
    assert res_override.ok is True


def test_add_carry_over_validation(controller: VacationController) -> None:
    # 1. Setup settings
    controller.model.save_settings(2025, 40.0, 10.0)  # max carryover 10h
    controller.model.save_settings(2026, 40.0, 10.0)

    # 2025 has 40h unused surplus
    allowance = controller.model.calculate_carry_over_allowance(2026)
    assert allowance["allowed_transfer"] == 10.0  # clamped by max_carry_over

    # 2. Try transferring 15h (Fails)
    res = controller.add_carry_over(2025, 2026, 15.0)
    assert res.ok is False
    assert "Cannot transfer" in res.errors[0]

    # 3. Try transferring 10h (Succeeds)
    res_ok = controller.add_carry_over(2025, 2026, 10.0)
    assert res_ok.ok is True
