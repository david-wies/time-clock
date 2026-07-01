"""Integration smoke tests: end-to-end flows through controller → model → DB."""

from __future__ import annotations

import pytest
from datetime import date, datetime, time

from controllers.time_clock_controller import TimeClockController
from controllers.vacation_controller import VacationController
from controllers.sickness_controller import SicknessController
from core.events import EventBus, Event
from core.hebrew_date import to_hebrew_label
from core.report import period_summary
from db.database import Database
from domain.enums import WorkType, VacationType
from domain.types import TimeRecord, VacationRecord, SicknessRecord
from models.sickness_model import SicknessModel
from models.time_clock_model import TimeClockModel
from models.vacation_model import VacationModel
from settings import SettingsManager


# ─────────────────────────── Fixtures ────────────────────────────────────────

@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def db() -> Database:
    return Database(db_path=":memory:")


@pytest.fixture
def settings(db: Database) -> SettingsManager:
    sm = SettingsManager(db)
    sm.set("work_day_targets", {0: 8.0, 1: 8.0, 2: 8.0, 3: 8.0, 4: 8.0, 5: 0.0, 6: 0.0})
    return sm


@pytest.fixture
def tc_model(db: Database, bus: EventBus) -> TimeClockModel:
    return TimeClockModel(db, bus)


@pytest.fixture
def vac_model(db: Database, bus: EventBus) -> VacationModel:
    return VacationModel(db, bus)


@pytest.fixture
def sick_model(db: Database, bus: EventBus) -> SicknessModel:
    return SicknessModel(db, bus)


@pytest.fixture
def tc_ctrl(tc_model: TimeClockModel, settings: SettingsManager) -> TimeClockController:
    def fixed_clock() -> datetime:
        return datetime(2026, 6, 26, 9, 0)
    return TimeClockController(tc_model, settings, clock=fixed_clock)


@pytest.fixture
def vac_ctrl(vac_model: VacationModel, settings: SettingsManager) -> VacationController:
    return VacationController(vac_model)


@pytest.fixture
def sick_ctrl(sick_model: SicknessModel) -> SicknessController:
    return SicknessController(sick_model)


# ─────────────────────── Hebrew date tests ────────────────────────────────────

def test_hebrew_label_returns_string() -> None:
    label = to_hebrew_label(date(2026, 6, 26))
    assert isinstance(label, str)
    assert len(label) > 0


def test_hebrew_label_known_date() -> None:
    # 26 June 2026 = 1 Tammuz 5786 (א' תמוז תשפ"ו)
    label = to_hebrew_label(date(2026, 6, 26))
    assert "זומת" in label  # to_hebrew_label reverses the string; "זומת" == "תמוז"[::-1]


def test_hebrew_label_rosh_hashana() -> None:
    # 23 Sep 2025 = 1 Tishri 5786 (Rosh Hashana; 22 Sep is still 29 Elul)
    label = to_hebrew_label(date(2025, 9, 23))
    assert "ירשת" in label  # to_hebrew_label reverses the string; "ירשת" == "תשרי"[::-1]


# ─────────────────── Clock-in / clock-out integration ─────────────────────────

def test_clock_in_creates_open_record(
    tc_ctrl: TimeClockController, tc_model: TimeClockModel
) -> None:
    result = tc_ctrl.clock_in(work_type=WorkType.REMOTE)
    assert result.ok
    open_records = tc_model.get_open_records_for_date(date(2026, 6, 26))
    assert len(open_records) == 1
    assert open_records[0].end_time is None
    assert open_records[0].work_type == WorkType.REMOTE


def test_clock_out_closes_open_record(
    tc_ctrl: TimeClockController, tc_model: TimeClockModel
) -> None:
    tc_ctrl.clock_in(work_type=WorkType.REMOTE)
    result = tc_ctrl.clock_out()
    assert result.ok
    open_records = tc_model.get_open_records_for_date(date(2026, 6, 26))
    assert len(open_records) == 0


def test_second_clock_in_blocked_without_force(
    tc_ctrl: TimeClockController,
) -> None:
    tc_ctrl.clock_in(work_type=WorkType.REMOTE)
    result = tc_ctrl.clock_in(work_type=WorkType.ROAD)
    assert not result.ok
    assert "OPEN_RECORD_EXISTS" in result.errors


def test_force_flag_bypasses_open_record_check(
    tc_ctrl: TimeClockController,
) -> None:
    tc_ctrl.clock_in(work_type=WorkType.REMOTE)
    result = tc_ctrl.clock_in(work_type=WorkType.ROAD, force=True)
    # force=True suppresses OPEN_RECORD_EXISTS — any remaining error is overlap, not the guard
    assert "OPEN_RECORD_EXISTS" not in result.errors


def test_add_edit_delete_record(
    tc_ctrl: TimeClockController, tc_model: TimeClockModel
) -> None:
    record = TimeRecord(
        id=None,
        date=date(2026, 6, 26),
        start_time=time(9, 0),
        end_time=time(17, 0),
        break_minutes=30,
        work_type=WorkType.IN_SITE,
        office="Office A",
        note="Test",
    )
    result = tc_ctrl.save_record(record)
    assert result.ok
    assert record.id is not None

    record.note = "Updated"
    result2 = tc_ctrl.save_record(record)
    assert result2.ok

    fetched = tc_model.get_record_by_id(record.id)
    assert fetched is not None
    assert fetched.note == "Updated"

    del_result = tc_ctrl.delete_record(record.id)
    assert del_result.ok
    assert tc_model.get_record_by_id(record.id) is None


def test_all_three_work_types(
    tc_ctrl: TimeClockController, tc_model: TimeClockModel
) -> None:
    slots = [(time(9, 0), time(10, 0)), (time(11, 0), time(12, 0)), (time(13, 0), time(14, 0))]
    for (wtype, office), (s, e) in zip(
        [(WorkType.IN_SITE, "Office A"), (WorkType.ROAD, None), (WorkType.REMOTE, None)],
        slots,
    ):
        r = TimeRecord(
            id=None,
            date=date(2026, 6, 25),
            start_time=s,
            end_time=e,
            break_minutes=0,
            work_type=wtype,
            office=office,
            note=None,
        )
        res = tc_ctrl.save_record(r)
        assert res.ok, f"Failed for {wtype}: {res.errors}"


# ─────────────────── Vacation integration ─────────────────────────────────────

def test_vacation_four_pool_types(
    vac_ctrl: VacationController, vac_model: VacationModel
) -> None:
    vac_model.save_settings(year=2026, hours_per_year=160.0, max_carry_over=40.0)
    # carry_over must go via add_carry_over(); test the other four pool types
    for i, vtype in enumerate([
        VacationType.ANNUAL_LEAVE, VacationType.PUBLIC_HOLIDAY,
        VacationType.SPECIAL_LEAVE, VacationType.UNPAID_LEAVE,
    ]):
        r = VacationRecord(
            id=None,
            date=date(2026, 6, i + 1),
            hours=8.0,
            vtype=vtype,
            note=None,
        )
        result = vac_ctrl.save_record(r)
        if not result.ok and "OVER_BALANCE_WARNING" in result.errors:
            result = vac_ctrl.save_record(r, confirm_over_balance=True)
        assert result.ok, f"Failed for {vtype}: {result.errors}"


def test_carry_over_flow(
    vac_ctrl: VacationController, vac_model: VacationModel
) -> None:
    vac_model.save_settings(year=2025, hours_per_year=160.0, max_carry_over=40.0)
    vac_model.save_settings(year=2026, hours_per_year=160.0, max_carry_over=40.0)
    result = vac_ctrl.add_carry_over(from_year=2025, to_year=2026, hours=20.0)
    assert result.ok, f"Carry-over failed: {result.errors}"

    summary = vac_model.calculate_vacation_summary(2026)
    assert summary.carry_over == 20.0
    assert summary.total_pool == 180.0


# ─────────────────── Sickness integration ─────────────────────────────────────

def test_sickness_add_and_convert(
    sick_ctrl: SicknessController, sick_model: SicknessModel
) -> None:
    sick_model.save_settings(year=2026, hours_per_year=80.0)
    r = SicknessRecord(id=None, date=date(2026, 6, 10), hours=8.0, note="Flu")
    result = sick_ctrl.save_record(r)
    assert result.ok

    summary = sick_model.calculate_sickness_summary(2026)
    assert summary.used_hours == 8.0


# ─────────────────── Report integration ───────────────────────────────────────

@pytest.fixture
def populated_db(
    tc_model: TimeClockModel,
    vac_model: VacationModel,
    sick_model: SicknessModel,
    settings: SettingsManager,
    tc_ctrl: TimeClockController,
    vac_ctrl: VacationController,
    sick_ctrl: SicknessController,
) -> tuple[TimeClockModel, VacationModel, SicknessModel, SettingsManager]:
    vac_model.save_settings(year=2026, hours_per_year=160.0, max_carry_over=40.0)
    sick_model.save_settings(year=2026, hours_per_year=80.0)
    settings.set("overtime_rate", 1.0)

    # Add two time records
    for d, s, e in [(date(2026, 6, 1), time(9, 0), time(17, 0)),
                    (date(2026, 6, 2), time(8, 0), time(16, 0))]:
        r = TimeRecord(id=None, date=d, start_time=s, end_time=e,
                       break_minutes=30, work_type=WorkType.REMOTE, office=None, note=None)
        tc_ctrl.save_record(r)

    # Vacation
    vr = VacationRecord(id=None, date=date(2026, 6, 5), hours=8.0,
                        vtype=VacationType.ANNUAL_LEAVE, note=None)
    vac_ctrl.save_record(vr, confirm_over_balance=True)

    # Sickness
    sr = SicknessRecord(id=None, date=date(2026, 6, 10), hours=8.0, note=None)
    sick_ctrl.save_record(sr)

    return tc_model, vac_model, sick_model, settings


def test_report_month(
    populated_db: tuple[TimeClockModel, VacationModel, SicknessModel, SettingsManager]
) -> None:
    tc_model, vac_model, sick_model, settings = populated_db
    data = period_summary(
        period_type="month", year=2026, month=6, quarter=None,
        model_tc=tc_model, model_vacation=vac_model,
        model_sickness=sick_model, settings=settings,
    )
    assert data.period_label == "June 2026"
    assert data.worked_hours > 0
    assert data.vac_used == 8.0
    assert data.sick_used_hours == 8.0
    assert data.monthly_rows == []


def test_report_quarter(
    populated_db: tuple[TimeClockModel, VacationModel, SicknessModel, SettingsManager]
) -> None:
    tc_model, vac_model, sick_model, settings = populated_db
    data = period_summary(
        period_type="quarter", year=2026, month=None, quarter=2,
        model_tc=tc_model, model_vacation=vac_model,
        model_sickness=sick_model, settings=settings,
    )
    assert data.period_label == "Q2 2026"
    assert len(data.monthly_rows) == 3
    months = [row.month for row in data.monthly_rows]
    assert months == [4, 5, 6]


def test_report_year(
    populated_db: tuple[TimeClockModel, VacationModel, SicknessModel, SettingsManager]
) -> None:
    tc_model, vac_model, sick_model, settings = populated_db
    data = period_summary(
        period_type="year", year=2026, month=None, quarter=None,
        model_tc=tc_model, model_vacation=vac_model,
        model_sickness=sick_model, settings=settings,
    )
    assert data.period_label == "2026"
    assert len(data.monthly_rows) == 12


# ─────────────────── Event bus integration ────────────────────────────────────

def test_event_published_on_clock_in(
    tc_ctrl: TimeClockController, bus: EventBus
) -> None:
    events_received: list[str] = []
    bus.subscribe(Event.TIME_RECORDS_CHANGED, lambda: events_received.append("changed"))
    tc_ctrl.clock_in(work_type=WorkType.REMOTE)
    assert "changed" in events_received


def test_event_unsubscribe(bus: EventBus) -> None:
    received: list[int] = []
    unsub = bus.subscribe(Event.SETTINGS_CHANGED, lambda: received.append(1))
    bus.publish(Event.SETTINGS_CHANGED)
    assert len(received) == 1
    unsub()
    bus.publish(Event.SETTINGS_CHANGED)
    assert len(received) == 1  # no new events after unsub


# ─────────────────── Settings persistence ─────────────────────────────────────

def test_settings_round_trip(settings: SettingsManager) -> None:
    settings.set("theme", "dark")
    assert settings.get("theme") == "dark"
    settings.set("minimize_to_tray", True)
    assert settings.get("minimize_to_tray") is True


def test_settings_default(settings: SettingsManager) -> None:
    assert settings.get("nonexistent_key", "fallback") == "fallback"
