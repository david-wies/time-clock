"""UI-only mode enums shared across view widgets."""

from enum import StrEnum

__all__ = ["ViewMode", "ExportTab", "ExportFormat"]


class ViewMode(StrEnum):
    WEEK = "week"
    MONTH = "month"


class ExportTab(StrEnum):
    TIME = "time"
    VACATION = "vacation"
    SICKNESS = "sickness"


class ExportFormat(StrEnum):
    CSV = "csv"
    EXCEL = "excel"
    PDF = "pdf"
