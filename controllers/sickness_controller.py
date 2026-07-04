import logging
import sqlite3
from datetime import date, timedelta

from domain.enums import WarningCode
from domain.types import Hours, Result, SicknessRecord, sickness_record_invariant_errors
from models.sickness_model import SicknessModel

logger = logging.getLogger(__name__)


def validate_sick_record(record: SicknessRecord) -> list[str]:
    """Pure validation function for SicknessRecord (enforces §7.3 table).

    The 0.5-24 bound is fixed policy (not context-dependent), but is kept
    here rather than in SicknessRecord.__post_init__: only the universal
    non-negative floor is enforced at construction (see task report for the
    "fold non-negative into __post_init__" decision). Note-length and that
    non-negative floor ARE context-free and are enforced unconditionally by
    SicknessRecord.__post_init__ at construction time — but
    SicknessController.save_record() re-runs them via
    sickness_record_invariant_errors() below, since __post_init__ never
    re-fires for a record fetched from the DB and then mutated in place.
    """
    errors = []

    if record.hours < 0.5 or record.hours > 24.0:
        errors.append("Hours must be between 0.5 and 24.")

    return errors


class SicknessController:
    def __init__(self, model: SicknessModel) -> None:
        self.model = model

    def save_record(
        self, record: SicknessRecord, confirm_over_balance: bool = False
    ) -> Result:
        """Validates and saves a SicknessRecord."""
        invariant_errors = sickness_record_invariant_errors(record)
        if invariant_errors:
            return Result(ok=False, errors=invariant_errors)

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
                "Database error while deleting sick record id=%s", record_id
            )
            return Result(ok=False, errors=[f"Database error: {e}"])

    def save_range(
        self,
        start_date: date,
        end_date: date,
        hours: float,
        note: str | None = None,
        confirm_over_balance: bool = False,
        document_path: str | None = None,
    ) -> Result:
        """Insert sick records for every day in [start_date, end_date] inclusive."""
        if end_date < start_date:
            return Result(ok=False, errors=["End date must be on or after start date."])
        if hours < 0.5 or hours > 24.0:
            return Result(ok=False, errors=["Hours must be between 0.5 and 24."])

        existing = self.model.get_records_in_date_range(start_date, end_date)
        if existing:
            conflict_dates = ", ".join(sorted(d.date.isoformat() for d in existing))
            return Result(
                ok=False,
                errors=[f"A sick record already exists for: {conflict_dates}."],
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

        # Note-length (and non-negative-hours) validity is a context-free
        # invariant enforced unconditionally by SicknessRecord.__post_init__
        # (domain/types.py) — construction raises ValueError instead of
        # silently accepting an invalid note, so it's caught here and
        # converted to a Result per this codebase's "controllers return
        # Result, never raise for expected validation failures" convention.
        try:
            records = [
                SicknessRecord(
                    id=None,
                    date=d,
                    hours=Hours(hours),
                    note=note,
                    document_path=document_path,
                )
                for d in dates
            ]
        except ValueError as e:
            return Result(ok=False, errors=[str(e)])

        try:
            self.model.insert_records_bulk(records)
            return Result(ok=True, errors=[])
        except sqlite3.Error as e:
            logger.exception(
                "Database error while saving sick record range %s..%s",
                start_date,
                end_date,
            )
            return Result(ok=False, errors=[f"Database error: {e}"])
