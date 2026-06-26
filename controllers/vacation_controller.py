from typing import Optional
from domain.types import VacationRecord, Result
from domain.enums import VacationType
from models.vacation_model import VacationModel

def validate_vacation_record(record: VacationRecord) -> list[str]:
    """Pure validation function for VacationRecord."""
    errors = []
    
    # 1. Bounds checking on hours
    if record.hours < 0.5 or record.hours > 24.0:
        errors.append("Hours must be between 0.5 and 24.")
        
    # 2. Note length
    if record.note and len(record.note) > 500:
        errors.append("Note is too long (max 500 characters).")
        
    return errors

class VacationController:
    def __init__(self, model: VacationModel) -> None:
        self.model = model

    def save_record(self, record: VacationRecord, confirm_over_balance: bool = False) -> Result:
        """Validates and saves a VacationRecord."""
        errors = validate_vacation_record(record)
        if errors:
            return Result(ok=False, errors=errors)

        # Check balance if this is a debit record (not carry-over or unpaid leave)
        is_debit = record.vtype in (
            VacationType.ANNUAL_LEAVE,
            VacationType.PUBLIC_HOLIDAY,
            VacationType.SPECIAL_LEAVE
        )
        
        if is_debit:
            year = record.date.year
            summary = self.model.calculate_vacation_summary(year)
            
            # If editing, subtract old record hours from used to calculate projected remaining
            old_hours = 0.0
            if record.id is not None:
                old_rec = self.model.get_record_by_id(record.id)
                if old_rec and old_rec.vtype in (
                    VacationType.ANNUAL_LEAVE,
                    VacationType.PUBLIC_HOLIDAY,
                    VacationType.SPECIAL_LEAVE
                ):
                    old_hours = old_rec.hours
            
            projected_remaining = summary["remaining"] + old_hours - record.hours
            
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

    def add_carry_over(self, from_year: int, to_year: int, hours: float) -> Result:
        """Validates and records a carry-over allocation."""
        if hours <= 0:
            return Result(ok=False, errors=["Hours to transfer must be greater than zero."])
            
        allowance = self.model.calculate_carry_over_allowance(to_year)
        allowed_max = allowance["allowed_transfer"]
        
        if hours > allowed_max:
            return Result(
                ok=False,
                errors=[f"Cannot transfer {hours:.1f} hours. Max allowed is {allowed_max:.1f} hours."]
            )
            
        try:
            self.model.add_carry_over(from_year, to_year, hours)
            return Result(ok=True, errors=[])
        except Exception as e:
            return Result(ok=False, errors=[f"Database error: {str(e)}"])

    def delete_record(self, record_id: int) -> Result:
        try:
            self.model.delete_record(record_id)
            return Result(ok=True, errors=[])
        except Exception as e:
            return Result(ok=False, errors=[f"Database error: {str(e)}"])
