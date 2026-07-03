import logging
import sqlite3

from domain.types import MiliuimRecord, Result
from models.miliuim_model import MiliuimModel

logger = logging.getLogger(__name__)


class MiliuimController:
    """Note: there is no free validate_miliuim_record() function anymore —
    every check it used to perform (start/end date required, end >= start,
    note length) was context-free and is now enforced unconditionally by
    MiliuimRecord.__post_init__. Only the overlap check remains here, since
    it needs other persisted records (context-dependent)."""

    def __init__(self, model: MiliuimModel) -> None:
        self.model = model

    def save_record(self, record: MiliuimRecord) -> Result:
        errors: list[str] = []
        existing = self.model.get_records_in_date_range(
            record.start_date, record.end_date)
        for other in existing:
            if other.id == record.id:
                continue
            errors.append(
                "Period overlaps with an existing Miliuim period "
                f"({other.start_date.isoformat()} – {other.end_date.isoformat()})."
            )
            break
        if errors:
            return Result(ok=False, errors=errors)

        try:
            if record.id is None:
                record_id = self.model.insert_record(record)
                record.id = record_id
            else:
                self.model.update_record(record)
            return Result(ok=True, errors=[])
        except sqlite3.Error as e:
            logger.exception(
                "Database error while saving Miliuim record %r", record)
            return Result(ok=False, errors=[f"Database error: {e}"])

    def delete_record(self, record_id: int) -> Result:
        try:
            self.model.delete_record(record_id)
            return Result(ok=True, errors=[])
        except sqlite3.Error as e:
            logger.exception(
                "Database error while deleting Miliuim record id=%s", record_id)
            return Result(ok=False, errors=[f"Database error: {e}"])
