"""UI-only mode enums shared across view widgets."""

from enum import StrEnum

__all__ = ["ViewMode", "ExportTab", "ExportFormat"]


class ViewMode(StrEnum):
    """Calendar view granularity: week or month."""

    WEEK = "week"
    MONTH = "month"


class ExportTab(StrEnum):
    """Record type selected for export: time, vacation, or sickness."""

    TIME = "time"
    VACATION = "vacation"
    SICKNESS = "sickness"


class ExportFormat(StrEnum):
    """Output file format for exports: CSV, Excel, or PDF."""

    CSV = "csv"
    EXCEL = "excel"
    PDF = "pdf"
