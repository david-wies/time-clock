"""Domain dataclasses and invariant helpers for all record types."""

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

import math
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any, Callable, ClassVar

from core.timeutil import duration
from domain.enums import VacationType, WorkType

_MAX_NOTE_LENGTH = 500


def _check_note_length(note: str | None, errors: list[str]) -> None:
    """Append the shared note-length error to `errors` if `note` exceeds
    `_MAX_NOTE_LENGTH`. Factored out of the four `*_invariant_errors`
    functions, which all enforce this identical universal invariant."""
    if note and len(note) > _MAX_NOTE_LENGTH:
        errors.append(f"Note is too long (max {_MAX_NOTE_LENGTH} characters).")


def _validate_note(value: str | None) -> str | None:
    """Single-field note-length check, raised immediately rather than
    collected into an error list. Used as a `_ValidatingRecord` validator
    (see below) so mutating `.note` on an existing record re-checks the
    same invariant `_check_note_length` enforces at construction time —
    reuses that helper rather than duplicating the condition/message."""
    errors: list[str] = []
    _check_note_length(value, errors)
    if errors:
        raise ValueError(errors[0])
    return value


class _ValidatingRecord:
    """Mixin that re-validates single-field invariants on every assignment,
    not just at construction.

    Plain (non-frozen) dataclasses only run `__post_init__` once, at
    construction — nothing stops later code from doing `record.hours = -5`
    and silently violating an invariant `__post_init__` was supposed to
    guarantee forever. Subclasses set a class-level `_VALIDATORS` dict
    mapping field name to a `callable(value) -> value` that raises
    `ValueError` on an invalid value (and may coerce/cast it, e.g. into
    `Hours`/`BreakMinutes`).

    Only *single-field* invariants belong in `_VALIDATORS` — a validator
    only ever sees the one new value being assigned, so it cannot check
    cross-field invariants (e.g. "end_date must be >= start_date") that
    depend on sibling fields. Those stay in `__post_init__`, which still
    only re-runs at construction, same as before this mixin existed.

    Validation is skipped while the instance is under construction — i.e.
    until `self._constructed` is set to `True` as the last line of
    `__post_init__` — so the dataclass-generated `__init__` can assign
    every field first and `__post_init__` can collect *all* violations via
    the class's `*_invariant_errors()` helper and raise them joined in one
    `ValueError`, exactly as before. Every assignment after that point
    (i.e. any mutation of an already-constructed record) re-validates
    immediately.
    """

    __slots__ = ()
    _VALIDATORS: ClassVar[dict[str, Callable[[Any], Any]]] = {}

    def __setattr__(self, name: str, value: object) -> None:
        validator = self._VALIDATORS.get(name)
        if validator is not None and getattr(self, "_constructed", False):
            value = validator(value)
        object.__setattr__(self, name, value)


class Hours(float):
    """A non-negative quantity of hours. Behaves as a plain ``float`` (arithmetic,
    formatting, sqlite3 binding) but rejects negative values at construction."""

    def __new__(cls, value: float) -> "Hours":
        v = float(value)
        if math.isnan(v) or math.isinf(v):
            raise ValueError("Hours must be non-negative.")
        if v < 0:
            raise ValueError("Hours must be non-negative.")
        return super().__new__(cls, v)


class BreakMinutes(int):
    """A non-negative quantity of break minutes. Behaves as a plain ``int``
    but rejects negative values at construction."""

    def __new__(cls, value: int) -> "BreakMinutes":
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            raise ValueError("Break minutes must be non-negative.")
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

    _check_note_length(record.note, errors)

    return errors


@dataclass(slots=True)
class TimeRecord(_ValidatingRecord):
    """A single clock-in/out record for one calendar day."""

    id: int | None
    date: date
    start_time: time
    end_time: time | None
    break_minutes: BreakMinutes
    work_type: WorkType
    office: str | None = None
    note: str | None = None
    document_path: str | None = None
    _constructed: bool = field(default=False, init=False, repr=False, compare=False)

    # break_minutes/note are single-field invariants, re-checked on every
    # mutation via _ValidatingRecord.__setattr__. The break-vs-shift-length
    # and work_type/office checks are cross-field (need start_time/end_time
    # or work_type/office together) and stay construction-only below.
    _VALIDATORS: ClassVar[dict[str, Callable[[Any], Any]]] = {
        "break_minutes": BreakMinutes,
        "note": _validate_note,
    }

    def __post_init__(self) -> None:
        # Context-free invariants only — checks that need other DB records
        # (overlap) or live settings stay in
        # controllers.time_clock_controller.validate_time_record().
        errors = time_record_invariant_errors(self)
        if errors:
            raise ValueError("; ".join(errors))
        self.break_minutes = BreakMinutes(self.break_minutes)
        self._constructed = True

    @property
    def is_open(self) -> bool:
        """Whether this record has no end time yet (still clocked in)."""
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

    _check_note_length(record.note, errors)

    return errors


@dataclass(slots=True)
class VacationRecord(_ValidatingRecord):
    """A single vacation day entry with its type, hours, and note."""

    id: int | None
    date: date
    hours: Hours
    vtype: VacationType
    note: str | None = None
    _constructed: bool = field(default=False, init=False, repr=False, compare=False)

    _VALIDATORS: ClassVar[dict[str, Callable[[Any], Any]]] = {
        "hours": Hours,
        "note": _validate_note,
    }

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
            raise ValueError("; ".join(errors))
        self.hours = Hours(self.hours)
        self._constructed = True


def sickness_record_invariant_errors(record: "SicknessRecord") -> list[str]:
    """Context-free invariants for SicknessRecord.

    The 0.5–24 bound is fixed business policy, not context-dependent, but is
    left in controllers.sickness_controller.validate_sick_record() unchanged
    — only the universal non-negative floor and note length are enforced
    here.

    Enforced unconditionally by SicknessRecord.__post_init__ at construction
    time. SicknessController.save_record() must call this again before
    persisting a record that was fetched and mutated rather than freshly
    constructed, since __post_init__ never re-runs on attribute mutation.
    save_range() does not need to: it always builds fresh SicknessRecord
    instances (never fetches-then-mutates), so __post_init__ already fires
    for every record it saves.
    """
    errors: list[str] = []

    if record.hours < 0:
        errors.append("Hours must be non-negative.")

    _check_note_length(record.note, errors)

    return errors


@dataclass(slots=True)
class SicknessRecord(_ValidatingRecord):
    """A single sick-leave entry for one calendar day."""

    id: int | None
    date: date
    hours: Hours
    note: str | None = None
    document_path: str | None = None
    _constructed: bool = field(default=False, init=False, repr=False, compare=False)

    _VALIDATORS: ClassVar[dict[str, Callable[[Any], Any]]] = {
        "hours": Hours,
        "note": _validate_note,
    }

    def __post_init__(self) -> None:
        errors = sickness_record_invariant_errors(self)
        if errors:
            raise ValueError("; ".join(errors))
        self.hours = Hours(self.hours)
        self._constructed = True


@dataclass(slots=True)
class Result:
    """Outcome of a controller operation: success flag plus any validation errors."""

    ok: bool
    errors: list[str]


@dataclass(slots=True)
class VacationSummary:
    """A year's vacation balance: allowance, carry-over, usage, and remaining hours."""

    allowance: float
    carry_over: float
    total_pool: float
    used: float
    remaining: float


@dataclass(slots=True)
class CarryOverAllowance:
    """The surplus vacation hours eligible to carry over into the next year."""

    prev_surplus: float
    max_carry_over: float
    already_transferred: float
    available_surplus: float
    allowed_transfer: float


@dataclass(slots=True)
class SicknessSummary:
    """A year's sick-leave balance: allowance, usage, and remaining hours."""

    allowance_hours: float
    used_hours: float
    remaining_hours: float


def _validate_workday_exception_hours(value: float) -> float:
    """Single-field non-negative check for WorkDayException.hours. Shared
    by __post_init__ (construction) and _VALIDATORS (post-construction
    mutation, via _ValidatingRecord) so the logic lives in one place.

    Delegates to `Hours`, which already rejects negative, NaN, and
    infinite values — reusing that check here instead of duplicating it
    also fixes NaN silently passing through the old `value < 0` comparison
    (NaN comparisons are always False in Python)."""
    try:
        return Hours(value)
    except TypeError as e:
        raise ValueError("Hours must be a non-negative number.") from e


@dataclass(slots=True)
class WorkDayException(_ValidatingRecord):
    """Override of a calendar day's expected work hours (holiday, short day, etc.)."""

    id: int
    date: date
    hours: float
    label: str | None
    _constructed: bool = field(default=False, init=False, repr=False, compare=False)

    _VALIDATORS: ClassVar[dict[str, Callable[[Any], Any]]] = {
        "hours": _validate_workday_exception_hours,
    }

    def __post_init__(self) -> None:
        self.hours = _validate_workday_exception_hours(self.hours)
        self._constructed = True


def _validate_carry_over_hours(value: float) -> float:
    """Single-field positive check for CarryOverLogEntry.hours. Shared by
    __post_init__ (construction) and _VALIDATORS (post-construction
    mutation, via _ValidatingRecord) so the logic lives in one place."""
    if value <= 0:
        raise ValueError("Hours must be positive.")
    return value


@dataclass(slots=True)
class CarryOverLogEntry(_ValidatingRecord):
    """A historical record of a vacation carry-over transfer between two years."""

    id: int
    from_year: int
    to_year: int
    hours: float
    transferred_at: datetime  # UTC
    _constructed: bool = field(default=False, init=False, repr=False, compare=False)

    _VALIDATORS: ClassVar[dict[str, Callable[[Any], Any]]] = {
        "hours": _validate_carry_over_hours,
    }

    def __post_init__(self) -> None:
        # Carry-over always moves surplus from the immediately preceding
        # year into the next one (DESIGN.md §10.2/§10.3: "prev_year_surplus"
        # is always to_year - 1, and VacationModel.add_carry_over()'s only
        # caller, views/carry_over_dialog.py, hardcodes
        # self._from_year = to_year - 1). from_year < to_year alone would be
        # too weak to catch a caller accidentally skipping or reversing a
        # year, so the exact one-year gap is enforced instead — this
        # cross-field check stays construction-only (a single-field
        # validator can't see both from_year and to_year together).
        if self.to_year != self.from_year + 1:
            raise ValueError("to_year must be exactly one year after from_year.")
        self.hours = _validate_carry_over_hours(self.hours)
        self._constructed = True


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

    _check_note_length(record.note, errors)

    return errors


@dataclass(slots=True)
class MiliuimRecord(_ValidatingRecord):
    """A single reserve-duty (miliuim) period spanning a start and end date."""

    id: int | None
    start_date: date
    end_date: date
    note: str | None = None
    document_path: str | None = None
    _constructed: bool = field(default=False, init=False, repr=False, compare=False)

    # end_date/start_date form a cross-field invariant (end >= start) that
    # a single-field validator can't see both sides of, so it stays
    # construction-only below. note is single-field and re-checked on
    # every mutation via _ValidatingRecord.__setattr__.
    _VALIDATORS: ClassVar[dict[str, Callable[[Any], Any]]] = {
        "note": _validate_note,
    }

    def __post_init__(self) -> None:
        errors = miliuim_record_invariant_errors(self)
        if errors:
            raise ValueError("; ".join(errors))
        self._constructed = True


@dataclass(slots=True)
class MiliuimSummary:
    """A year's aggregate reserve-duty (miliuim) totals: period count and total days."""

    period_count: int
    total_days: int


@dataclass(slots=True)
class PeriodBalance:
    """A period's worked-vs-target hour balance, including weighted overtime."""

    worked_hours: float
    target_hours: float
    balance: float
    weighted_overtime: float
    days_in_period: int
