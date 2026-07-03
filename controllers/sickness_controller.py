import logging
import sqlite3
from datetime import date, timedelta
from typing import Optional
from domain.types import SicknessRecord, Result
from domain.enums import WarningCode
from models.sickness_model import SicknessModel

logger = logging.getLogger(__name__)


def validate_sick_record(record: SicknessRecord) -> list[str]:
    """Pure validation function for SicknessRecord (enforces §7.3 table)."""
    errors = []

    if record.date is None:
        errors.append("Please enter a valid date.")

    if record.hours < 0.5 or record.hours > 24.0:
        errors.append("Hours must be between 0.5 and 24.")

    if record.note and len(record.note) > 500:
        errors.append("Note is too long (max 500 characters).")

    return errors


class SicknessController:
    def __init__(self, model: SicknessModel) -> None:
        self.model = model

    def save_record(self, record: SicknessRecord, confirm_over_balance: bool = False) -> Result:
        """Validates and saves a SicknessRecord."""
        errors = validate_sick_record(record)
        if errors:
            return Result(ok=False, errors=errors)

        year = record.date.year
        summary = self.model.calculate_sickness_summary(year)

        old_hours = 0.0
        if record.id is not None:
            old_rec = self.model.get_record_by_id(record.id)
            if old_rec and old_rec.date.year == year:
                old_hours = old_rec.hours

        projected_used = summary.used_hours - old_hours + record.hours
        projected_remaining = summary.allowance_hours - projected_used

        if projected_remaining < 0 and not confirm_over_balance:
            return Result(ok=False, errors=[WarningCode.OVER_BALANCE.value])

        try:
            if record.id is None:
                record_id = self.model.insert_record(record)
                record.id = record_id
            else:
                self.model.update_record(record)
            return Result(ok=True, errors=[])
        except sqlite3.Error as e:
            logger.exception("Database error while saving sick record %r", record)
            return Result(ok=False, errors=[f"Database error: {e}"])

    def delete_record(self, record_id: int) -> Result:
        try:
            self.model.delete_record(record_id)
            return Result(ok=True, errors=[])
        except sqlite3.Error as e:
            logger.exception(
                "Database error while deleting sick record id=%s", record_id)
            return Result(ok=False, errors=[f"Database error: {e}"])

    def save_range(
        self,
        start_date: date,
        end_date: date,
        hours: float,
        note: Optional[str] = None,
        confirm_over_balance: bool = False,
        document_path: Optional[str] = None,
    ) -> Result:
        """Insert sick records for every day in [start_date, end_date] inclusive."""
        if end_date < start_date:
            return Result(ok=False, errors=["End date must be on or after start date."])
        if hours < 0.5 or hours > 24.0:
            return Result(ok=False, errors=["Hours must be between 0.5 and 24."])
        if note and len(note) > 500:
            return Result(ok=False, errors=["Note is too long (max 500 characters)."])

        existing = self.model.get_records_in_date_range(start_date, end_date)
        if existing:
            conflict_dates = ", ".join(
                sorted(d.date.isoformat() for d in existing))
            return Result(
                ok=False,
                errors=[
                    f"A sick record already exists for: {conflict_dates}."],
            )

        dates: list[date] = []
        cur = start_date
        while cur <= end_date:
            dates.append(cur)
            cur += timedelta(days=1)

        if not confirm_over_balance:
            year_date_counts: dict[int, int] = {}
            for d in dates:
                year_date_counts[d.year] = year_date_counts.get(d.year, 0) + 1
            for yr, count in year_date_counts.items():
                summary = self.model.calculate_sickness_summary(yr)
                if summary.remaining_hours - hours * count < 0:
                    return Result(ok=False, errors=[WarningCode.OVER_BALANCE.value])

        records = [SicknessRecord(
            id=None, date=d, hours=hours, note=note,
            document_path=document_path) for d in dates]
        try:
            self.model.insert_records_bulk(records)
            return Result(ok=True, errors=[])
        except sqlite3.Error as e:
            logger.exception(
                "Database error while saving sick record range %s..%s", start_date, end_date)
            return Result(ok=False, errors=[f"Database error: {e}"])
