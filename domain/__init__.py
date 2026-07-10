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
    set_generated_id,
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
    "set_generated_id",
]
