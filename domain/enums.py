"""Enumerated domain types shared across models, controllers, and views."""

from enum import IntEnum, StrEnum

__all__ = [
    "WorkType",
    "VacationType",
    "Weekday",
    "WarningCode",
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
    """A code identifying a non-fatal warning condition surfaced to the UI."""

    OVERNIGHT_SHIFT = "OVERNIGHT_SHIFT_WARNING"
    OPEN_RECORD_EXISTS = "OPEN_RECORD_EXISTS"
    MULTIPLE_OPEN_RECORDS = "MULTIPLE_OPEN_RECORDS"
    OVER_BALANCE = "OVER_BALANCE_WARNING"


class PeriodType(StrEnum):
    """The granularity of a reporting period: month, quarter, or year."""

    MONTH = "month"
    QUARTER = "quarter"
    YEAR = "year"


class OvertimePeriod(StrEnum):
    """The window over which overtime is calculated: week, month, or year."""

    WEEK = "week"
    MONTH = "month"
    YEAR = "year"
