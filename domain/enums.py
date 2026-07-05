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
    IN_SITE = "in_site"
    ROAD = "road"
    REMOTE = "remote"


class VacationType(StrEnum):
    ANNUAL_LEAVE = "annual_leave"
    PUBLIC_HOLIDAY = "public_holiday"
    SPECIAL_LEAVE = "special_leave"
    UNPAID_LEAVE = "unpaid_leave"
    CARRY_OVER = "carry_over"


class Weekday(IntEnum):
    MON = 0
    TUE = 1
    WED = 2
    THU = 3
    FRI = 4
    SAT = 5
    SUN = 6


class WarningCode(StrEnum):
    OVERNIGHT_SHIFT = "OVERNIGHT_SHIFT_WARNING"
    OPEN_RECORD_EXISTS = "OPEN_RECORD_EXISTS"
    MULTIPLE_OPEN_RECORDS = "MULTIPLE_OPEN_RECORDS"
    OVER_BALANCE = "OVER_BALANCE_WARNING"


class PeriodType(StrEnum):
    MONTH = "month"
    QUARTER = "quarter"
    YEAR = "year"


class OvertimePeriod(StrEnum):
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"
