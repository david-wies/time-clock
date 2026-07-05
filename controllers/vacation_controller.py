"""Vacation controller: validates input and mediates model ↔ view."""

import logging

from controllers.time_clock_controller import DatabaseErrorGuard
from domain.enums import VacationType, WarningCode
from domain.types import Result, VacationRecord, vacation_record_invariant_errors
from models.vacation_model import VacationModel

logger = logging.getLogger(__name__)

_DEBIT_VACATION_TYPES = (
    VacationType.ANNUAL_LEAVE,
    VacationType.PUBLIC_HOLIDAY,
    VacationType.SPECIAL_LEAVE,
)


def validate_vacation_record(
    record: VacationRecord, max_hours: float = 24.0
) -> list[str]:
    """Pure validation function for VacationRecord (enforces §6.5 table).

    max_hours comes from a live settings lookup
    (VacationModel.get_daily_target_for_date()) at save time, so this bound
    is context-dependent and cannot move into VacationRecord.__post_init__.
    The note-length and non-negative-hours checks ARE context-free and are
    enforced unconditionally by VacationRecord.__post_init__ instead — but
    VacationController.save_record() re-runs them via
    vacation_record_invariant_errors() below, since __post_init__ never
    re-fires for a record fetched from the DB and then mutated in place.
    """
    errors = []

    if record.vtype == VacationType.PUBLIC_HOLIDAY:
        if record.hours < 0 or record.hours > max_hours:
            errors.append(f"Hours must be between 0 and {max_hours:.1f}.")
    else:
        if record.hours < 0.5 or record.hours > max_hours:
            errors.append(f"Hours must be between 0.5 and {max_hours:.1f}.")

    return errors


class VacationController:
    """Validates and mediates vacation record CRUD between view and model."""

    def __init__(self, model: VacationModel) -> None:
        self.model = model

    def save_record(
        self, record: VacationRecord, confirm_over_balance: bool = False
    ) -> Result:
        """Validates and saves a VacationRecord."""
        # NOT dead code: VacationRecord.__post_init__ deliberately does not
        # reject vtype=CARRY_OVER (it must remain constructible so records
        # read back from the DB via VacationModel._row_to_record() — which
        # includes carry-over rows inserted by add_carry_over() — don't
        # crash the Vacation tab / export dialog). This guard is what stops
        # such a record (however a caller obtained one) from being routed
        # through the general debit/credit save path instead of
        # add_carry_over().
        if record.vtype == VacationType.CARRY_OVER:
            return Result(
                ok=False, errors=["Use add_carry_over() to record carry-over hours."]
            )

        invariant_errors = vacation_record_invariant_errors(record)
        if invariant_errors:
            return Result(ok=False, errors=invariant_errors)

        max_hours = self.model.get_daily_target_for_date(record.date)
        if max_hours == 0.0:
            max_hours = 8.0  # weekend/day-off: use 8h as reference cap

        errors = validate_vacation_record(record, max_hours)
        if errors:
            return Result(ok=False, errors=errors)

        # Check balance if this is a debit record (not carry-over or unpaid leave)
        is_debit = record.vtype in _DEBIT_VACATION_TYPES

        if is_debit:
            year = record.date.year
            summary = self.model.calculate_vacation_summary(year)

            # If editing, subtract old record hours from used to calculate
            # projected remaining
            old_hours = 0.0
            if record.id is not None:
                old_rec = self.model.get_record_by_id(record.id)
                if old_rec and old_rec.vtype in _DEBIT_VACATION_TYPES:
                    old_hours = old_rec.hours

            projected_remaining = summary.remaining + old_hours - record.hours

            if projected_remaining < 0 and not confirm_over_balance:
                return Result(ok=False, errors=[WarningCode.OVER_BALANCE.value])

        guard = DatabaseErrorGuard(
            logger, "Database error while saving vacation record %r", record
        )
        with guard:
            if record.id is None:
                record_id = self.model.insert_record(record)
                record.id = record_id
            else:
                self.model.update_record(record)
            return Result(ok=True, errors=[])
        assert guard.result is not None
        return guard.result

    def add_carry_over(self, from_year: int, to_year: int, hours: float) -> Result:
        """Validates and records a carry-over allocation."""
        if hours <= 0:
            return Result(
                ok=False, errors=["Hours to transfer must be greater than zero."]
            )

        allowance = self.model.calculate_carry_over_allowance(to_year)
        allowed_max = allowance.allowed_transfer

        if hours > allowed_max:
            return Result(
                ok=False,
                errors=[
                    f"Cannot transfer {hours:.1f} hours. "
                    f"Max allowed is {allowed_max:.1f} hours."
                ],
            )

        guard = DatabaseErrorGuard(
            logger,
            "Database error while adding carry-over from_year=%s to_year=%s",
            from_year,
            to_year,
        )
        with guard:
            self.model.add_carry_over(from_year, to_year, hours)
            return Result(ok=True, errors=[])
        assert guard.result is not None
        return guard.result

    def delete_record(self, record_id: int) -> Result:
        """Delete the vacation record with the given id."""
        guard = DatabaseErrorGuard(
            logger, "Database error while deleting vacation record id=%s", record_id
        )
        with guard:
            self.model.delete_record(record_id)
            return Result(ok=True, errors=[])
        assert guard.result is not None
        return guard.result
