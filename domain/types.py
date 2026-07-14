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
    "set_generated_id",
    "time_record_invariant_errors",
    "vacation_record_invariant_errors",
    "sickness_record_invariant_errors",
    "miliuim_record_invariant_errors",
]

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any, ClassVar, Protocol

from core.timeutil import duration
from domain.enums import VacationType, WorkType

_MAX_NOTE_LENGTH = 500


def _check_note_length(note: str | None, errors: list[str]) -> None:
    """Append the shared note-length error to `errors` if `note` exceeds
    `_MAX_NOTE_LENGTH`. Factored out of the four `*_invariant_errors`
    functions, which all enforce this identical universal invariant."""
    if note and len(note) > _MAX_NOTE_LENGTH:
        errors.append(f"Note is too long (max {_MAX_NOTE_LENGTH} characters).")


class _ValidatingRecord:
    """Mixin that re-validates single-field invariants on every assignment,
    not just at construction.

    Used by WorkDayException — the one record type in this module that is
    still mutable, because `date`/`id`/`label` have no invariant to enforce
    today. VacationRecord, SicknessRecord, MiliuimRecord, TimeRecord, and
    CarryOverLogEntry are frozen instead (see VacationRecord's docstring
    below for why), so they do not use this mixin.

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

    def __new__(cls, value: float) -> Hours:
        v = float(value)
        if math.isnan(v) or math.isinf(v):
            raise ValueError("Hours must be non-negative.")
        if v < 0:
            raise ValueError("Hours must be non-negative.")
        return super().__new__(cls, v)


class BreakMinutes(int):
    """A non-negative quantity of break minutes. Behaves as a plain ``int``
    but rejects negative values at construction."""

    def __new__(cls, value: int) -> BreakMinutes:
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            raise ValueError("Break minutes must be non-negative.")
        v = int(value)
        if v < 0:
            raise ValueError("Break minutes must be non-negative.")
        return super().__new__(cls, v)


class _HasId(Protocol):
    """Structural type for `set_generated_id()` — any record with an
    `id: int | None` attribute, without committing to a specific record
    class. Narrower than `Any`: it still lets mypy reject a call passing an
    object with no `id` attribute at all. A read-only `@property` (not a
    plain attribute) because every record type is a frozen dataclass —
    `id` itself is never reassigned through ordinary attribute access;
    `set_generated_id()` only ever backfills it via the documented
    `object.__setattr__` escape hatch, which structural Protocol matching
    doesn't see."""

    @property
    def id(self) -> int | None:
        """The record's database id, or None before it has been persisted."""


def time_record_invariant_errors(record: TimeRecord) -> list[str]:
    """Context-free invariants for TimeRecord — checks that need only the
    record's own fields, not other DB records (overlap) or live settings.

    Enforced unconditionally by TimeRecord.__post_init__ — both at
    construction and on every `dataclasses.replace()`, which is the only way
    to derive a changed TimeRecord now that it is frozen (see
    controllers.time_clock_controller.TimeClockController.clock_out()).
    TimeClockController.save_record() still calls this function directly as
    defense-in-depth before persisting, in case a caller was handed an
    already-validated record from somewhere this module doesn't control.
    """
    errors: list[str] = []

    break_minutes_valid = True
    try:
        BreakMinutes(record.break_minutes)
    except (ValueError, TypeError) as e:
        errors.append(str(e))
        break_minutes_valid = False

    if record.end_time is not None and break_minutes_valid:
        raw_duration = duration(record.start_time, record.end_time, 0)
        break_hours = record.break_minutes / 60.0
        if break_hours > raw_duration:
            errors.append("Break cannot exceed shift length.")

    office_missing = not (record.office and record.office.strip())
    if record.work_type == WorkType.IN_SITE and office_missing:
        errors.append("Please select or enter an office.")

    _check_note_length(record.note, errors)

    return errors


@dataclass(frozen=True, slots=True)
class TimeRecord:
    """A single clock-in/out record for one calendar day.

    Frozen rather than a `_ValidatingRecord` subclass like the other record
    types: TimeRecord's invariants span multiple fields (break vs. shift
    length, office required for in-site work) rather than single ones, so a
    per-field `_VALIDATORS` map can't cover them anyway. Freezing removes
    in-place mutation entirely — the only way to change a field on an
    existing TimeRecord is `dataclasses.replace(record, field=value)`, which
    builds a new instance and reruns `__post_init__` in full, so there is no
    way to end up with a record whose fields were valid individually but
    invalid together (e.g. a fetched record whose `end_time` was set without
    re-checking `break_minutes` against the new shift length). See
    controllers.time_clock_controller.TimeClockController.clock_out().
    """

    __hash__ = None  # type: ignore[assignment]

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
            raise ValueError("; ".join(errors))
        # object.__setattr__ bypasses the frozen-dataclass __setattr__ that
        # would otherwise reject this — the standard pattern for a frozen
        # dataclass that needs to normalize a field in __post_init__.
        object.__setattr__(self, "break_minutes", BreakMinutes(self.break_minutes))

    @property
    def is_open(self) -> bool:
        """Whether this record has no end time yet (still clocked in)."""
        return self.end_time is None


def vacation_record_invariant_errors(record: VacationRecord) -> list[str]:
    """Context-free invariants for VacationRecord.

    The bounds on `hours` (0.5 vs 0 minimum, live max_hours cap) are
    context-dependent (depend on vtype and same-day settings lookups) and
    stay in controllers.vacation_controller.validate_vacation_record().
    Only the universal non-negative floor and note length are checked here.

    Enforced unconditionally by VacationRecord.__post_init__ — both at
    construction and on every `dataclasses.replace()`, which is the only way
    to derive a changed VacationRecord now that it is frozen (see
    controllers.vacation_controller.VacationController.save_record(), which
    backfills the DB-generated `id` via the `object.__setattr__` escape
    hatch instead — `id` is not part of this invariant). VacationController
    .save_record() still calls this function directly as defense-in-depth
    before persisting, in case a caller was handed an already-validated
    record from somewhere this module doesn't control.
    """
    errors: list[str] = []

    try:
        Hours(record.hours)
    except (ValueError, TypeError) as e:
        errors.append(str(e))

    _check_note_length(record.note, errors)

    return errors


@dataclass(frozen=True, slots=True)
class VacationRecord:
    """A single vacation day entry with its type, hours, and note.

    Frozen rather than a `_ValidatingRecord` subclass — mirrors TimeRecord
    (domain/types.py): freezing removes in-place mutation entirely, so the
    only way to change a field on an existing VacationRecord is
    `dataclasses.replace(record, field=value)`, which builds a new instance
    and reruns `__post_init__` in full. See
    controllers.vacation_controller.VacationController.save_record() for the
    one legitimate post-construction assignment (backfilling the
    DB-generated `id`), which uses the documented `object.__setattr__`
    escape hatch instead of ordinary assignment, exactly like TimeRecord's
    equivalent in TimeClockController.save_record().
    """

    __hash__ = None  # type: ignore[assignment]

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
            raise ValueError("; ".join(errors))
        # object.__setattr__ bypasses the frozen-dataclass __setattr__ that
        # would otherwise reject this — the standard pattern for a frozen
        # dataclass that needs to normalize a field in __post_init__ (see
        # TimeRecord.__post_init__).
        object.__setattr__(self, "hours", Hours(self.hours))


def sickness_record_invariant_errors(record: SicknessRecord) -> list[str]:
    """Context-free invariants for SicknessRecord.

    The 0.5–24 bound is fixed business policy, not context-dependent, but is
    left in controllers.sickness_controller.validate_sick_record() unchanged
    — only the universal non-negative floor and note length are enforced
    here.

    Enforced unconditionally by SicknessRecord.__post_init__ — both at
    construction and on every `dataclasses.replace()`, which is the only way
    to derive a changed SicknessRecord now that it is frozen (see
    controllers.sickness_controller.SicknessController.save_record(), which
    backfills the DB-generated `id` via the `object.__setattr__` escape
    hatch instead — `id` is not part of this invariant). SicknessController
    .save_record() still calls this function directly as defense-in-depth
    before persisting, in case a caller was handed an already-validated
    record from somewhere this module doesn't control. save_range() does
    not need to: it always builds fresh SicknessRecord instances, so
    __post_init__ already fires for every record it saves.
    """
    errors: list[str] = []

    try:
        Hours(record.hours)
    except (ValueError, TypeError) as e:
        errors.append(str(e))

    _check_note_length(record.note, errors)

    return errors


@dataclass(frozen=True, slots=True)
class SicknessRecord:
    """A single sick-leave entry for one calendar day.

    Frozen rather than a `_ValidatingRecord` subclass — see VacationRecord's
    docstring (domain/types.py) for the rationale; SicknessRecord mirrors it
    exactly.
    """

    __hash__ = None  # type: ignore[assignment]

    id: int | None
    date: date
    hours: Hours
    note: str | None = None
    document_path: str | None = None

    def __post_init__(self) -> None:
        errors = sickness_record_invariant_errors(self)
        if errors:
            raise ValueError("; ".join(errors))
        object.__setattr__(self, "hours", Hours(self.hours))


@dataclass(frozen=True, slots=True)
class Result:
    """Outcome of a controller operation: success flag, blocking errors, and
    non-blocking warnings.

    `errors` and `warnings` are deliberately separate fields rather than one
    overloaded `errors` list read differently depending on `ok` — `errors`
    holds the reason(s) a `ok=False` result failed (a caller must be able to
    trust that `not ok` implies `errors` explains why), while `warnings`
    holds non-blocking codes (e.g. `WarningCode.OVERNIGHT_SHIFT`) that may
    accompany an `ok=True` result. `__post_init__` enforces both halves of
    this contract that a type checker can't: a false result must carry a
    reason, and a true result must not carry one — otherwise a caller that
    only checks `if not result.ok` (the documented, correct way to consume a
    Result) would silently drop a real error attached to an `ok=True`
    result.

    Frozen, with `errors`/`warnings` stored as `tuple[str, ...]` rather than
    `list[str]` — nothing but `__post_init__` should ever be able to touch
    these fields after construction, otherwise `result.errors.append(...)`
    could silently corrupt the `ok=False ⟺ errors non-empty` invariant this
    class exists to guarantee. Construction still accepts any iterable
    (callers overwhelmingly pass a `list[str]` literal, e.g.
    `Result(ok=False, errors=["msg"])`) — `__post_init__` converts it into a
    real tuple via the `object.__setattr__` escape hatch, the same pattern
    used by every other frozen record in this module to normalize a field.
    """

    ok: bool
    errors: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        errors = tuple(self.errors)
        warnings = tuple(self.warnings)
        if not self.ok and not errors:
            raise ValueError("Result(ok=False, ...) must carry at least one error.")
        if self.ok and errors:
            raise ValueError("Result(ok=True, ...) must not carry any errors.")
        object.__setattr__(self, "errors", errors)
        object.__setattr__(self, "warnings", warnings)


@dataclass(slots=True)
class VacationSummary:
    """A year's vacation balance: allowance, carry-over, usage, and remaining hours.

    `total_pool` and `remaining` are computed properties, not stored fields
    — VacationModel.calculate_vacation_summary() (their only construction
    site) always derives them as `allowance + carry_over` and `total_pool -
    used` respectively, with no conditional branch that ever computes them
    differently. Storing them as independent fields would let a future
    caller pass an inconsistent value; computing them here makes that
    impossible.
    """

    allowance: float
    carry_over: float
    used: float

    @property
    def total_pool(self) -> float:
        """Total hours available this year: allowance plus carried-over surplus."""
        return self.allowance + self.carry_over

    @property
    def remaining(self) -> float:
        """Hours still unused: the total pool minus hours already used."""
        return self.total_pool - self.used


@dataclass(slots=True)
class CarryOverAllowance:
    """The surplus vacation hours eligible to carry over into the next year.

    `available_surplus` and `allowed_transfer` are both computed properties,
    not stored fields — VacationModel.calculate_carry_over_allowance() (this
    dataclass's only construction site) always derives `available_surplus`
    as `max(0, prev_surplus - already_transferred)`, and `allowed_transfer`
    as `max(0, min(max_carry_over - already_transferred,
    available_surplus))`, with no conditional branch that ever computes
    either differently. Storing them as independent fields would let a
    future caller pass an inconsistent value; computing them here makes
    that impossible, mirroring VacationSummary/SicknessSummary/PeriodBalance
    above.
    """

    prev_surplus: float
    max_carry_over: float
    already_transferred: float

    @property
    def available_surplus(self) -> float:
        """Prior-year surplus still left after any already-transferred hours."""
        return max(0.0, self.prev_surplus - self.already_transferred)

    @property
    def allowed_transfer(self) -> float:
        """Surplus permitted to carry over, capped by the max-carry-over limit."""
        return max(
            0.0,
            min(self.max_carry_over - self.already_transferred, self.available_surplus),
        )


@dataclass(slots=True)
class SicknessSummary:
    """A year's sick-leave balance: allowance, usage, and remaining hours.

    `remaining_hours` is a computed property, not a stored field —
    SicknessModel.calculate_sickness_summary() (its only construction site)
    always derives it as `allowance_hours - used_hours`, with no
    conditional branch that ever computes it differently.
    """

    allowance_hours: float
    used_hours: float

    @property
    def remaining_hours(self) -> float:
        """Sick-leave hours still available: allowance minus hours used."""
        return self.allowance_hours - self.used_hours


@dataclass(slots=True)
class WorkDayException(_ValidatingRecord):
    """Override of a calendar day's expected work hours (holiday, short day, etc.)."""

    id: int
    date: date
    hours: Hours
    label: str | None
    _constructed: bool = field(default=False, init=False, repr=False, compare=False)

    # Reuses Hours (domain/types.py, near the top) instead of hand-rolling a
    # second non-negative/finite check — Hours already rejects negative,
    # NaN, and infinite values, so there is nothing left for a wrapper here
    # to add.
    _VALIDATORS: ClassVar[dict[str, Callable[[Any], Any]]] = {
        "hours": Hours,
    }

    def __post_init__(self) -> None:
        self.hours = Hours(self.hours)
        self._constructed = True


def _positive_hours(value: float) -> Hours:
    """Single-field strictly-positive check for CarryOverLogEntry.hours.
    Shared by __post_init__ (construction) and _VALIDATORS (post-
    construction mutation, via _ValidatingRecord) so the logic lives in one
    place.

    CarryOverLogEntry.hours must be strictly positive, not merely
    non-negative like plain `Hours` — this layers that extra requirement on
    top of `Hours` instead of hand-rolling the non-negative/finite check a
    second time. Delegating the first half to `Hours` also fixes NaN/inf
    silently passing through the old bare `value <= 0` comparison (NaN
    comparisons are always False in Python, and inf > 0 is True)."""
    hours = Hours(value)
    if hours <= 0:
        raise ValueError("Hours must be positive.")
    return hours


@dataclass(frozen=True, slots=True)
class CarryOverLogEntry:
    """A historical record of a vacation carry-over transfer between two years.

    Frozen rather than a `_ValidatingRecord` subclass — see MiliuimRecord's
    docstring (domain/types.py) for the rationale, which applies here
    identically: `to_year == from_year + 1` is a genuine cross-field
    invariant that a `_ValidatingRecord`-style per-field `_VALIDATORS` map
    could never re-check on mutation (it only ever sees the one field being
    assigned, e.g. `entry.from_year = 1900` would silently succeed even
    though it violates the invariant against the still-unchanged `to_year`).
    Freezing is what makes it impossible to violate post-construction, not
    just conventionally re-checked. Unlike TimeRecord/VacationRecord/
    SicknessRecord/MiliuimRecord, CarryOverLogEntry never needs the
    `object.__setattr__` id-backfill pattern — its only construction sites
    (models/vacation_model.py) already know the DB-generated `id` at
    construction time.
    """

    __hash__ = None  # type: ignore[assignment]

    id: int
    from_year: int
    to_year: int
    hours: Hours
    transferred_at: datetime  # UTC

    def __post_init__(self) -> None:
        # Carry-over always moves surplus from the immediately preceding
        # year into the next one (design/data-flow.md §10.2/§10.3: "prev_year_surplus"
        # is always to_year - 1, and VacationModel.add_carry_over()'s only
        # caller, views/carry_over_dialog.py, hardcodes
        # self._from_year = to_year - 1). from_year < to_year alone would be
        # too weak to catch a caller accidentally skipping or reversing a
        # year, so the exact one-year gap is enforced instead.
        if self.to_year != self.from_year + 1:
            raise ValueError("to_year must be exactly one year after from_year.")
        # object.__setattr__ bypasses the frozen-dataclass __setattr__ that
        # would otherwise reject this — the standard pattern for a frozen
        # dataclass that needs to normalize a field in __post_init__ (see
        # TimeRecord.__post_init__).
        object.__setattr__(self, "hours", _positive_hours(self.hours))


def miliuim_record_invariant_errors(record: MiliuimRecord) -> list[str]:
    """Context-free invariants for MiliuimRecord.

    Enforced unconditionally by MiliuimRecord.__post_init__ — both at
    construction and on every `dataclasses.replace()`, which is the only way
    to derive a changed MiliuimRecord now that it is frozen (see
    controllers.miliuim_controller.MiliuimController.save_record(), which
    backfills the DB-generated `id` via the `object.__setattr__` escape
    hatch instead — `id` is not part of this invariant). MiliuimController
    .save_record() still calls this function directly as defense-in-depth
    before persisting, in case a caller was handed an already-validated
    record from somewhere this module doesn't control.

    `record.end_date < record.start_date` raises an unhandled TypeError,
    not a clean ValueError, if either date is None — that can only happen
    if a caller bypasses the `date` (not `date | None`) type annotation on
    both fields, since MiliuimRecord itself never allows constructing with a
    None date. MiliuimController.save_record() catches that TypeError and
    converts it to a Result, per this codebase's "controllers return
    Result, never raise for expected validation failures" convention.
    """
    errors: list[str] = []

    if record.end_date < record.start_date:
        errors.append("End date must be on or after start date.")

    _check_note_length(record.note, errors)

    return errors


@dataclass(frozen=True, slots=True)
class MiliuimRecord:
    """A single reserve-duty (miliuim) period spanning a start and end date.

    Frozen rather than a `_ValidatingRecord` subclass — see VacationRecord's
    docstring (domain/types.py) for the rationale. This matters more here
    than for VacationRecord/SicknessRecord: `end_date >= start_date` is a
    genuine cross-field invariant that a `_ValidatingRecord`-style
    per-field `_VALIDATORS` map could never re-check on mutation (it only
    ever sees the one field being assigned) — freezing is what makes it
    impossible to violate post-construction, not just conventionally
    re-checked.
    """

    __hash__ = None  # type: ignore[assignment]

    id: int | None
    start_date: date
    end_date: date
    note: str | None = None
    document_path: str | None = None

    def __post_init__(self) -> None:
        errors = miliuim_record_invariant_errors(self)
        if errors:
            raise ValueError("; ".join(errors))


def set_generated_id(record: _HasId, record_id: int) -> None:
    """Backfills a DB-generated id onto a frozen record instance via the
    object.__setattr__ escape hatch. id never participates in any record's
    invariant checks, so this bypass is inert with respect to validation.

    Factored out of the four controllers (time_clock_controller.py,
    vacation_controller.py, sickness_controller.py, miliuim_controller.py)
    that each duplicated this exact `object.__setattr__(record, "id", ...)`
    line after inserting a frozen TimeRecord/VacationRecord/SicknessRecord/
    MiliuimRecord and getting back the DB-generated primary key.
    """
    object.__setattr__(record, "id", record_id)


@dataclass(slots=True)
class MiliuimSummary:
    """A year's aggregate reserve-duty (miliuim) totals: period count and total days."""

    period_count: int
    total_days: int


@dataclass(slots=True)
class PeriodBalance:
    """A period's worked-vs-target hour balance, including weighted overtime.

    `balance` and `weighted_overtime` are both computed properties, not
    stored fields — core.balance.period_balance_from_grouped() (this
    dataclass's only construction site) always derives `balance` as
    `worked_hours - target_hours`, and `weighted_overtime` as `balance *
    overtime_rate` when `balance` is positive (surplus) or plain `balance`
    otherwise (deficit is never rate-adjusted), with no conditional branch
    that ever computes either differently. `overtime_rate` is retained as a
    stored field precisely so `weighted_overtime` can be recomputed from
    `balance` alone instead of being passed in pre-computed.
    """

    worked_hours: float
    target_hours: float
    overtime_rate: float
    days_in_period: int

    @property
    def balance(self) -> float:
        """Signed hours over (positive) or under (negative) the period target."""
        return self.worked_hours - self.target_hours

    @property
    def weighted_overtime(self) -> float:
        """Balance with any positive surplus scaled by the overtime rate."""
        if self.balance > 0:
            return self.balance * self.overtime_rate
        return self.balance
