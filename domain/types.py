__all__ = ["TimeRecord", "VacationRecord", "SicknessRecord",
           "MiliuimRecord", "MiliuimSummary", "Result"]

from dataclasses import dataclass
from datetime import date, time
from typing import Optional

from domain.enums import WorkType, VacationType


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


@dataclass(slots=True)
class SicknessRecord:
    id: Optional[int]
    date: date
    hours: float
    note: Optional[str] = None
    document_path: Optional[str] = None


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
    date: str        # ISO 8601
    hours: float
    label: Optional[str]


@dataclass(slots=True)
class CarryOverLogEntry:
    id: int
    from_year: int
    to_year: int
    hours: float
    transferred_at: str  # UTC datetime string


@dataclass(slots=True)
class MiliuimRecord:
    id: Optional[int]
    start_date: date
    end_date: date
    note: Optional[str] = None
    document_path: Optional[str] = None


@dataclass(slots=True)
class MiliuimSummary:
    period_count: int
    total_days: int
