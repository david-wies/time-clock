__all__ = ["TimeRecord", "VacationRecord", "SicknessRecord",
           "MiliuimRecord", "MiliuimSummary", "Result", "PeriodBalance"]

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Optional

from domain.enums import WorkType, VacationType
from core.timeutil import duration

_MAX_NOTE_LENGTH = 500


@dataclass(slots=True)
class TimeRecord:
    id: Optional[int]
    date: date
    start_time: time
    end_time: Optional[time]
    break_minutes: int
    work_type: WorkType
    office: Optional[str] = None
    note: Optional[str] = None
    document_path: Optional[str] = None

    def __post_init__(self) -> None:
        # Context-free invariants only — checks that need other DB records
        # (overlap) or live settings stay in
        # controllers.time_clock_controller.validate_time_record().
        if self.break_minutes < 0:
            raise ValueError("Break minutes must be non-negative.")

        if self.end_time is not None:
            raw_duration = duration(self.start_time, self.end_time, 0)
            break_hours = self.break_minutes / 60.0
            if break_hours > raw_duration:
                raise ValueError("Break cannot exceed shift length.")

        office_missing = not (self.office and self.office.strip())
        if self.work_type == WorkType.IN_SITE and office_missing:
            raise ValueError("Please select or enter an office.")

        if self.note and len(self.note) > _MAX_NOTE_LENGTH:
            raise ValueError(
                f"Note is too long (max {_MAX_NOTE_LENGTH} characters).")

    @property
    def is_open(self) -> bool:
        return self.end_time is None


@dataclass(slots=True)
class VacationRecord:
    id: Optional[int]
    date: date
    hours: float
    vtype: VacationType
    note: Optional[str] = None

    def __post_init__(self) -> None:
        # NOTE: vtype == VacationType.CARRY_OVER is deliberately NOT rejected
        # here. VacationModel.add_carry_over() inserts a 'carry_over' row
        # directly into the vacation_record table via raw SQL (it never
        # constructs a VacationRecord), but VacationModel._row_to_record()
        # (used by get_records_for_year()/get_record_by_id()) reconstructs a
        # VacationRecord from *every* row in that table when reading it back
        # — including carry-over rows. views/vacation_tab.py and
        # views/export_dialog.py both read carry-over records back through
        # that exact path to display/export them. Rejecting CARRY_OVER at
        # construction would crash the Vacation tab and CSV/PDF export for
        # any year containing a carry-over transfer. The user-facing guard
        # against *creating* one by hand is the removal of the CARRY_OVER
        # dropdown option in views/vacation_record_dialog.py, plus the
        # existing VacationController.save_record() check.
        #
        # The bounds on `hours` (0.5 vs 0 minimum, live max_hours cap) are
        # context-dependent (depend on vtype and same-day settings lookups)
        # and stay in controllers.vacation_controller.validate_vacation_record().
        if self.hours < 0:
            raise ValueError("Hours must be non-negative.")

        if self.note and len(self.note) > _MAX_NOTE_LENGTH:
            raise ValueError(
                f"Note is too long (max {_MAX_NOTE_LENGTH} characters).")


@dataclass(slots=True)
class SicknessRecord:
    id: Optional[int]
    date: date
    hours: float
    note: Optional[str] = None
    document_path: Optional[str] = None

    def __post_init__(self) -> None:
        # The 0.5–24 bound is fixed business policy, not context-dependent,
        # but is left in controllers.sickness_controller.validate_sick_record()
        # unchanged (see task report) — only the universal non-negative floor
        # is enforced here.
        if self.hours < 0:
            raise ValueError("Hours must be non-negative.")

        if self.note and len(self.note) > _MAX_NOTE_LENGTH:
            raise ValueError(
                f"Note is too long (max {_MAX_NOTE_LENGTH} characters).")


@dataclass(slots=True)
class Result:
    ok: bool
    errors: list[str]


@dataclass(slots=True)
class VacationSummary:
    allowance: float
    carry_over: float
    total_pool: float
    used: float
    remaining: float


@dataclass(slots=True)
class CarryOverAllowance:
    prev_surplus: float
    max_carry_over: float
    already_transferred: float
    available_surplus: float
    allowed_transfer: float


@dataclass(slots=True)
class SicknessSummary:
    allowance_hours: float
    used_hours: float
    remaining_hours: float


@dataclass(slots=True)
class WorkDayException:
    id: int
    date: date
    hours: float
    label: Optional[str]


@dataclass(slots=True)
class CarryOverLogEntry:
    id: int
    from_year: int
    to_year: int
    hours: float
    transferred_at: datetime  # UTC


@dataclass(slots=True)
class MiliuimRecord:
    id: Optional[int]
    start_date: date
    end_date: date
    note: Optional[str] = None
    document_path: Optional[str] = None

    def __post_init__(self) -> None:
        if self.end_date < self.start_date:
            raise ValueError("End date must be on or after start date.")

        if self.note and len(self.note) > _MAX_NOTE_LENGTH:
            raise ValueError(
                f"Note is too long (max {_MAX_NOTE_LENGTH} characters).")


@dataclass(slots=True)
class MiliuimSummary:
    period_count: int
    total_days: int


@dataclass(slots=True)
class PeriodBalance:
    worked_hours: float
    target_hours: float
    balance: float
    weighted_overtime: float
    days_in_period: int
