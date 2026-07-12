"""Enumerated domain types shared across models, controllers, and views."""

from enum import IntEnum, StrEnum

__all__ = [
    "WorkType",
    "VacationType",
    "Weekday",
    "WarningCode",
    "RECORD_NOT_FOUND_MESSAGE",
    "RECORD_NOT_FOUND_OPEN_RECORD_MESSAGE",
    "RecordEntity",
    "RecordAction",
    "PeriodType",
    "OvertimePeriod",
]


class WorkType(StrEnum):
    """Where a work shift was performed: on-site, on the road, or remote."""

    IN_SITE = "in_site"
    ROAD = "road"
    REMOTE = "remote"


class VacationType(StrEnum):
    """The category of a vacation day entry (annual leave, public holiday, etc.)."""

    ANNUAL_LEAVE = "annual_leave"
    PUBLIC_HOLIDAY = "public_holiday"
    SPECIAL_LEAVE = "special_leave"
    UNPAID_LEAVE = "unpaid_leave"
    CARRY_OVER = "carry_over"


class Weekday(IntEnum):
    """A day of the week, Monday-first, matching Python's date.weekday() ordering."""

    MON = 0
    TUE = 1
    WED = 2
    THU = 3
    FRI = 4
    SAT = 5
    SUN = 6


class WarningCode(StrEnum):
    """A code identifying a non-fatal warning condition surfaced to the UI.

    `blocking` marks whether this code belongs in `Result.errors` — the
    view must handle it specially (a `force`/`confirm_*` re-call, or a
    data reload for `RECORD_NOT_FOUND`) — or is purely informational
    (and belongs in `Result.warnings`)."""

    blocking: bool

    def __new__(cls, value: str, blocking: bool) -> WarningCode:
        obj = str.__new__(cls, value)
        obj._value_ = value
        obj.blocking = blocking
        return obj

    OVERNIGHT_SHIFT = ("OVERNIGHT_SHIFT_WARNING", False)
    OPEN_RECORD_EXISTS = ("OPEN_RECORD_EXISTS", True)
    MULTIPLE_OPEN_RECORDS = ("MULTIPLE_OPEN_RECORDS", True)
    OVER_BALANCE = ("OVER_BALANCE_WARNING", True)
    # The record targeted by an update/delete no longer exists (a stale-UI
    # race: it was already deleted elsewhere). Views own the user-facing
    # wording; on this code they should inform the user, reload their data
    # so the phantom row disappears, and close any edit dialog.
    RECORD_NOT_FOUND = ("RECORD_NOT_FOUND", True)


# Shared user-facing copy for WarningCode.RECORD_NOT_FOUND, factored out so
# the many view call sites that handle this code don't each hand-roll their
# own near-identical sentence. Views still own *how* they present it (title,
# messagebox variant, and any context-specific suffix) — these constants
# only capture the wording that would otherwise be duplicated verbatim.

# Used as-is by the record dialogs (save) and by the tab delete/remove
# handlers (time clock, vacation, sickness, miliuim) — identical across all
# of those call sites.
RECORD_NOT_FOUND_MESSAGE = (
    "This record no longer exists — it may have already been deleted "
    "elsewhere. The list will refresh."
)

# Base sentence for the open-clock-in-record variant of RECORD_NOT_FOUND.
# The tray icon's clock-out handler uses this as-is (no list/display to
# refresh there); the time-clock tab's clock-out handler appends its own
# " The display will refresh." suffix.
RECORD_NOT_FOUND_OPEN_RECORD_MESSAGE = (
    "The open clock-in record no longer exists — it may have already "
    "been deleted elsewhere."
)


class RecordEntity(StrEnum):
    """The kind of domain record a RecordNotFoundError refers to.

    One member per model that calls raise_if_no_rows() from its
    update_record()/delete_record() (models/time_clock_model.py,
    models/vacation_model.py, models/sickness_model.py,
    models/miliuim_model.py), mirroring the record dataclasses in
    domain/types.py."""

    TIME_RECORD = "time_record"
    VACATION_RECORD = "vacation_record"
    SICKNESS_RECORD = "sickness_record"
    MILIUIM_RECORD = "miliuim_record"


class RecordAction(StrEnum):
    """The mutating operation that was attempted against a record which
    turned out to be missing — used by RecordNotFoundError to describe
    what raced with what (e.g. an update that lost to a concurrent
    delete)."""

    UPDATE = "update"
    DELETE = "delete"


class PeriodType(StrEnum):
    """The granularity of a reporting period: month, quarter, or year."""

    MONTH = "month"
    QUARTER = "quarter"
    YEAR = "year"


# UI-only for now (not load-bearing): this enum only supplies the choices for
# the settings dialog's overtime-period dropdown. SettingsManager.get/set store
# the "overtime_period" key as a raw JSON string with no enum validation, and no
# balance/overtime logic consults these members yet — don't assume a stored
# value is guaranteed to be one of them.
class OvertimePeriod(StrEnum):
    """The window over which overtime is calculated: week, month, or year."""

    WEEK = "week"
    MONTH = "month"
    YEAR = "year"
