from domain.types import MiliuimRecord, Result
from models.miliuim_model import MiliuimModel


def validate_miliuim_record(record: MiliuimRecord) -> list[str]:
    errors = []
    if record.start_date is None:
        errors.append("Please enter a valid start date.")
    if record.end_date is None:
        errors.append("Please enter a valid end date.")
    if record.start_date and record.end_date and record.end_date < record.start_date:
        errors.append("End date must be on or after start date.")
    if record.note and len(record.note) > 500:
        errors.append("Note is too long (max 500 characters).")
    return errors


class MiliuimController:
    def __init__(self, model: MiliuimModel) -> None:
        self.model = model

    def save_record(self, record: MiliuimRecord) -> Result:
        errors = validate_miliuim_record(record)
        if errors:
            return Result(ok=False, errors=errors)
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
