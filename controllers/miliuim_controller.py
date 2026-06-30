from datetime import date, timedelta
from typing import Optional
from domain.types import MiliuimRecord, Result
from models.miliuim_model import MiliuimModel


def validate_miliuim_record(record: MiliuimRecord) -> list[str]:
    errors = []
    if record.date is None:
        errors.append("Please enter a valid date.")
    if record.hours < 0.5 or record.hours > 24.0:
        errors.append("Hours must be between 0.5 and 24.")
    if record.note and len(record.note) > 500:
        errors.append("Note is too long (max 500 characters).")
    return errors


class MiliuimController:
    def __init__(self, model: MiliuimModel) -> None:
        self.model = model

    def save_record(self, record: MiliuimRecord, confirm_over_balance: bool = False) -> Result:
        errors = validate_miliuim_record(record)
        if errors:
            return Result(ok=False, errors=errors)

        year = record.date.year
        summary = self.model.calculate_summary(year)

        if summary.allowance_hours > 0.0:
            old_hours = 0.0
            if record.id is not None:
                old_rec = self.model.get_record_by_id(record.id)
                if old_rec:
                    old_hours = old_rec.hours
            projected_used = summary.used_hours - old_hours + record.hours
            projected_remaining = summary.allowance_hours - projected_used
            if projected_remaining < 0 and not confirm_over_balance:
                return Result(ok=False, errors=["OVER_BALANCE_WARNING"])

        try:
            if record.id is None:
                record_id = self.model.insert_record(record)
                record.id = record_id
            else:
                self.model.update_record(record)
            return Result(ok=True, errors=[])
        except Exception as e:
            return Result(ok=False, errors=[f"Database error: {str(e)}"])

    def save_range(
        self,
        start_date: date,
        end_date: date,
        hours: float,
        note: Optional[str] = None,
        confirm_over_balance: bool = False,
    ) -> Result:
        """Insert miliuim records for every day in [start_date, end_date] inclusive."""
        if end_date < start_date:
            return Result(ok=False, errors=["End date must be on or after start date."])
        if hours < 0.5 or hours > 24.0:
            return Result(ok=False, errors=["Hours must be between 0.5 and 24."])
        if note and len(note) > 500:
            return Result(ok=False, errors=["Note is too long (max 500 characters)."])

        dates: list[date] = []
        cur = start_date
        while cur <= end_date:
            dates.append(cur)
            cur += timedelta(days=1)

        year = start_date.year
        summary = self.model.calculate_summary(year)
        if summary.allowance_hours > 0.0:
            total_new = hours * len(dates)
            if summary.remaining_hours - total_new < 0 and not confirm_over_balance:
                return Result(ok=False, errors=["OVER_BALANCE_WARNING"])

        try:
            for d in dates:
                self.model.insert_record(MiliuimRecord(id=None, date=d, hours=hours, note=note))
            return Result(ok=True, errors=[])
        except Exception as e:
            return Result(ok=False, errors=[f"Database error: {str(e)}"])

    def delete_record(self, record_id: int) -> Result:
        try:
            self.model.delete_record(record_id)
            return Result(ok=True, errors=[])
        except Exception as e:
            return Result(ok=False, errors=[f"Database error: {str(e)}"])
