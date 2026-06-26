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

@dataclass(slots=True)
class Result:
    ok: bool
    errors: list[str]
