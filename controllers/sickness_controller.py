from typing import Optional
from domain.types import SicknessRecord, Result
from models.sickness_model import SicknessModel

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

        # Check balance
        year = record.date.year
        summary = self.model.calculate_sickness_summary(year)
        
        # If editing, subtract old record day equivalent from used to calculate projected remaining
        old_days_equiv = 0.0
        if record.id is not None:
            old_rec = self.model.get_record_by_id(record.id)
            if old_rec:
                old_days_equiv = self.model.get_day_equivalent(old_rec.date, old_rec.hours)
                
        projected_used_days = summary.used_days - old_days_equiv + self.model.get_day_equivalent(record.date, record.hours)
        projected_remaining = summary.allowance - projected_used_days
        
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

    def delete_record(self, record_id: int) -> Result:
        try:
            self.model.delete_record(record_id)
            return Result(ok=True, errors=[])
        except Exception as e:
            return Result(ok=False, errors=[f"Database error: {str(e)}"])
