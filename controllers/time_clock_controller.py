from datetime import date, time, datetime
from typing import Optional, Callable

from domain.types import TimeRecord, Result
from domain.enums import WorkType
from models.time_clock_model import TimeClockModel
from settings import SettingsManager
from core.timeutil import duration


def times_overlap(s1: time, e1: Optional[time], s2: time, e2: Optional[time]) -> bool:
    """Checks if two time intervals on the same day overlap."""
    start1 = s1.hour * 60 + s1.minute
    end1 = (e1.hour * 60 + e1.minute) if e1 else 1440

    start2 = s2.hour * 60 + s2.minute
    end2 = (e2.hour * 60 + e2.minute) if e2 else 1440

    # Handle overnight shift wrapping for comparison (capped at 24h)
    if e1 and end1 < start1:
        end1 = 1440
    if e2 and end2 < start2:
        end2 = 1440

    return start1 < end2 and start2 < end1


def validate_time_record(record: TimeRecord, existing_records: list[TimeRecord]) -> list[str]:
    """Pure validation function for TimeRecord (enforces §5.6 table)."""
    errors = []

    # date required
    if record.date is None:
        errors.append("Please enter a valid date.")

    # start_time required
    if record.start_time is None:
        errors.append("Start time must be in HH:MM format.")

    if record.end_time is not None and record.start_time is not None:
        start_mins = record.start_time.hour * 60 + record.start_time.minute
        end_mins = record.end_time.hour * 60 + record.end_time.minute

        if end_mins == start_mins:
            # Zero-length record — warning only (caller decides; no block per §12 #6)
            pass
        elif end_mins < start_mins:
            # Overnight shift — warn, not error (§5.7)
            errors.append("OVERNIGHT_SHIFT_WARNING")

        # Break must not exceed shift duration
        raw_dur = duration(record.start_time, record.end_time, 0)
        break_hours = record.break_minutes / 60.0
        if break_hours > raw_dur:
            errors.append("Break cannot exceed shift length.")

    if record.break_minutes < 0:
        errors.append("Break minutes must be non-negative.")

    # work_type required
    if record.work_type is None:
        errors.append("Please select a work type.")

    # office required for in_site
    if record.work_type == WorkType.IN_SITE:
        if not record.office or not record.office.strip():
            errors.append("Please select or enter an office.")

    # note length
    if record.note and len(record.note) > 500:
        errors.append("Note is too long (max 500 characters).")

    # overlap check (only if date and start_time valid)
    if record.date is not None and record.start_time is not None:
        for existing in existing_records:
            if existing.id == record.id:
                continue
            if times_overlap(record.start_time, record.end_time, existing.start_time, existing.end_time):
                errors.append("Record overlaps with an existing time record.")
                break

    return errors


class TimeClockController:
    def __init__(
        self,
        model: TimeClockModel,
        settings: SettingsManager,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self.model = model
        self.settings = settings
        self._clock = clock or datetime.now

    def save_record(self, record: TimeRecord) -> Result:
        """Validates and saves (inserts or updates) a TimeRecord."""
        existing = self.model.get_records_by_date(record.date)
        errors = validate_time_record(record, existing)

        # OVERNIGHT_SHIFT_WARNING is not a blocking error — filter it out before blocking
        blocking = [e for e in errors if e != "OVERNIGHT_SHIFT_WARNING"]
        if blocking:
            return Result(ok=False, errors=blocking)

        try:
            if record.id is None:
                record_id = self.model.insert_record(record)
                record.id = record_id
            else:
                self.model.update_record(record)

            self.settings.set("last_used_work_type", record.work_type.value)
            # may contain OVERNIGHT_SHIFT_WARNING
            return Result(ok=True, errors=errors)
        except Exception as e:
            return Result(ok=False, errors=[f"Database error: {str(e)}"])

    def clock_in(self, work_type: Optional[WorkType] = None, force: bool = False) -> Result:
        """
        Clocks in the user. Creates a new record with start_time = now.
        Returns Result(ok=False, errors=["OPEN_RECORD_EXISTS"]) if a today-open record exists
        and force=False.
        """
        open_today = self.model.get_open_records_for_date(self._clock().date())
        if open_today and not force:
            return Result(ok=False, errors=["OPEN_RECORD_EXISTS"])

        if work_type is None:
            last_wt = self.settings.get("last_used_work_type")
            if last_wt:
                try:
                    work_type = WorkType(last_wt)
                except ValueError:
                    work_type = WorkType.REMOTE
            else:
                work_type = WorkType.REMOTE

        office = None
        if work_type == WorkType.IN_SITE:
            offices = self.settings.get("offices")
            office = offices[0] if offices else "Main Office"

        now = self._clock()
        record = TimeRecord(
            id=None,
            date=now.date(),
            start_time=now.time().replace(second=0, microsecond=0),
            end_time=None,
            break_minutes=0,
            work_type=work_type,
            office=office,
            note=""
        )

        existing = self.model.get_records_by_date(record.date)
        errors = validate_time_record(record, existing)
        blocking = [e for e in errors if e != "OVERNIGHT_SHIFT_WARNING"]
        if blocking:
            return Result(ok=False, errors=blocking)

        try:
            self.model.insert_record(record)
            return Result(ok=True, errors=[])
        except Exception as e:
            return Result(ok=False, errors=[f"Database error: {str(e)}"])

    def clock_out(self, record_id: Optional[int] = None) -> Result:
        """
        Clocks out the user. Sets end_time = now on today's active open record.
        If multiple open records exist today and record_id is None, returns
        Result(ok=False, errors=["MULTIPLE_OPEN_RECORDS"]).
        """
        open_today = self.model.get_open_records_for_date(self._clock().date())
        if not open_today:
            return Result(ok=False, errors=["No active clock-in found."])

        target_record = None
        if record_id is not None:
            for rec in open_today:
                if rec.id == record_id:
                    target_record = rec
                    break
            if not target_record:
                return Result(ok=False, errors=["Specified clock-in record not found."])
        else:
            if len(open_today) > 1:
                return Result(ok=False, errors=["MULTIPLE_OPEN_RECORDS"])
            target_record = open_today[0]

        now = self._clock()
        target_record.end_time = now.time().replace(second=0, microsecond=0)

        existing = self.model.get_records_by_date(target_record.date)
        existing_for_validation = [
            r for r in existing if r.id == target_record.id or r.end_time is not None]
        errors = validate_time_record(target_record, existing_for_validation)
        blocking = [e for e in errors if e != "OVERNIGHT_SHIFT_WARNING"]
        if blocking:
            return Result(ok=False, errors=blocking)

        try:
            self.model.update_record(target_record)
            return Result(ok=True, errors=errors)
        except Exception as e:
            return Result(ok=False, errors=[f"Database error: {str(e)}"])

    def delete_record(self, record_id: int) -> Result:
        try:
            self.model.delete_record(record_id)
            return Result(ok=True, errors=[])
        except Exception as e:
            return Result(ok=False, errors=[f"Database error: {str(e)}"])
