"""Domain package: dataclasses shared across models, controllers, and views."""

from domain.types import (
    CarryOverAllowance,
    CarryOverLogEntry,
    Result,
    SicknessRecord,
    SicknessSummary,
    TimeRecord,
    VacationRecord,
    VacationSummary,
    WorkDayException,
)

__all__ = [
    "TimeRecord",
    "VacationRecord",
    "SicknessRecord",
    "Result",
    "VacationSummary",
    "CarryOverAllowance",
    "SicknessSummary",
    "WorkDayException",
    "CarryOverLogEntry",
]
