__all__ = [
    "Hours",
    "BreakMinutes",
    "TimeRecord",
    "VacationRecord",
    "SicknessRecord",
    "MiliuimRecord",
    "MiliuimSummary",
    "Result",
    "PeriodBalance",
    "time_record_invariant_errors",
    "vacation_record_invariant_errors",
    "sickness_record_invariant_errors",
    "miliuim_record_invariant_errors",
]

from dataclasses import dataclass
from datetime import date, datetime, time

from core.timeutil import duration
from domain.enums import VacationType, WorkType

_MAX_NOTE_LENGTH = 500


class Hours(float):
    """A non-negative quantity of hours. Behaves as a plain ``float`` (arithmetic,
    formatting, sqlite3 binding) but rejects negative values at construction."""

    def __new__(cls, value: float) -> "Hours":
        v = float(value)
        if v < 0:
            raise ValueError("Hours must be non-negative.")
        return super().__new__(cls, v)


class BreakMinutes(int):
    """A non-negative quantity of break minutes. Behaves as a plain ``int``
    but rejects negative values at construction."""

    def __new__(cls, value: int) -> "BreakMinutes":
        v = int(value)
        if v < 0:
            raise ValueError("Break minutes must be non-negative.")
        return super().__new__(cls, v)


def time_record_invariant_errors(record: "TimeRecord") -> list[str]:
    """Context-free invariants for TimeRecord — checks that need only the
    record's own fields, not other DB records (overlap) or live settings.

    Enforced unconditionally by TimeRecord.__post_init__ at construction
    time. Controllers must call this again before save_record()/clock_out()
    persist a record that was fetched and mutated rather than freshly
    constructed, since __post_init__ never re-runs on attribute mutation —
    see controllers.time_clock_controller.TimeClockController.save_record()
    and .clock_out().
    """
    errors: list[str] = []

    if record.break_minutes < 0:
        errors.append("Break minutes must be non-negative.")

    if record.end_time is not None:
        raw_duration = duration(record.start_time, record.end_time, 0)
        break_hours = record.break_minutes / 60.0
        if break_hours > raw_duration:
            errors.append("Break cannot exceed shift length.")

    office_missing = not (record.office and record.office.strip())
    if record.work_type == WorkType.IN_SITE and office_missing:
        errors.append("Please select or enter an office.")

    if record.note and len(record.note) > _MAX_NOTE_LENGTH:
        errors.append(f"Note is too long (max {_MAX_NOTE_LENGTH} characters).")

    return errors


@dataclass(slots=True)
class TimeRecord:
    id: int | None
    date: date
    start_time: time
    end_time: time | None
    break_minutes: BreakMinutes
    work_type: WorkType
    office: str | None = None
    note: str | None = None
    document_path: str | None = None

    def __post_init__(self) -> None:
        # Context-free invariants only — checks that need other DB records
        # (overlap) or live settings stay in
        # controllers.time_clock_controller.validate_time_record().
        errors = time_record_invariant_errors(self)
        if errors:
            raise ValueError(errors[0])
        self.break_minutes = BreakMinutes(self.break_minutes)

    @property
    def is_open(self) -> bool:
        return self.end_time is None


def vacation_record_invariant_errors(record: "VacationRecord") -> list[str]:
    """Context-free invariants for VacationRecord.

    The bounds on `hours` (0.5 vs 0 minimum, live max_hours cap) are
    context-dependent (depend on vtype and same-day settings lookups) and
    stay in controllers.vacation_controller.validate_vacation_record().
    Only the universal non-negative floor and note length are checked here.

    Enforced unconditionally by VacationRecord.__post_init__ at construction
    time. VacationController.save_record() must call this again before
    persisting a record that was fetched and mutated rather than freshly
    constructed, since __post_init__ never re-runs on attribute mutation.
    """
    errors: list[str] = []

    if record.hours < 0:
        errors.append("Hours must be non-negative.")

    if record.note and len(record.note) > _MAX_NOTE_LENGTH:
        errors.append(f"Note is too long (max {_MAX_NOTE_LENGTH} characters).")

    return errors


@dataclass(slots=True)
class VacationRecord:
    id: int | None
    date: date
    hours: Hours
    vtype: VacationType
    note: str | None = None

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
        errors = vacation_record_invariant_errors(self)
        if errors:
            raise ValueError(errors[0])
        self.hours = Hours(self.hours)


def sickness_record_invariant_errors(record: "SicknessRecord") -> list[str]:
    """Context-free invariants for SicknessRecord.

    The 0.5–24 bound is fixed business policy, not context-dependent, but is
    left in controllers.sickness_controller.validate_sick_record() unchanged
    (see task report) — only the universal non-negative floor and note
    length are enforced here.

    Enforced unconditionally by SicknessRecord.__post_init__ at construction
    time. SicknessController.save_record()/save_range() must call this again
    before persisting a record that was fetched and mutated rather than
    freshly constructed, since __post_init__ never re-runs on attribute
    mutation.
    """
    errors: list[str] = []

    if record.hours < 0:
        errors.append("Hours must be non-negative.")

    if record.note and len(record.note) > _MAX_NOTE_LENGTH:
        errors.append(f"Note is too long (max {_MAX_NOTE_LENGTH} characters).")

    return errors


@dataclass(slots=True)
class SicknessRecord:
    id: int | None
    date: date
    hours: Hours
    note: str | None = None
    document_path: str | None = None

    def __post_init__(self) -> None:
        errors = sickness_record_invariant_errors(self)
        if errors:
            raise ValueError(errors[0])
        self.hours = Hours(self.hours)


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
    label: str | None


@dataclass(slots=True)
class CarryOverLogEntry:
    id: int
    from_year: int
    to_year: int
    hours: float
    transferred_at: datetime  # UTC


def miliuim_record_invariant_errors(record: "MiliuimRecord") -> list[str]:
    """Context-free invariants for MiliuimRecord.

    Enforced unconditionally by MiliuimRecord.__post_init__ at construction
    time. MiliuimController.save_record() must call this again before
    persisting a record that was fetched and mutated rather than freshly
    constructed, since __post_init__ never re-runs on attribute mutation.
    """
    errors: list[str] = []

    if record.end_date < record.start_date:
        errors.append("End date must be on or after start date.")

    if record.note and len(record.note) > _MAX_NOTE_LENGTH:
        errors.append(f"Note is too long (max {_MAX_NOTE_LENGTH} characters).")

    return errors


@dataclass(slots=True)
class MiliuimRecord:
    id: int | None
    start_date: date
    end_date: date
    note: str | None = None
    document_path: str | None = None

    def __post_init__(self) -> None:
        errors = miliuim_record_invariant_errors(self)
        if errors:
            raise ValueError(errors[0])


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
