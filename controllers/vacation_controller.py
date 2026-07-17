"""Vacation controller: validates input and mediates model ↔ view."""

import logging

from controllers.time_clock_controller import (
    DatabaseErrorGuard,
    over_balance_decision,
)
from domain.enums import VacationType, WarningCode
from domain.types import (
    Result,
    VacationGrant,
    VacationRecord,
    set_generated_id,
    vacation_grant_invariant_errors,
    vacation_record_invariant_errors,
)
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
    enforced unconditionally by VacationRecord.__post_init__ instead —
    VacationController.save_record() still re-runs them via
    vacation_record_invariant_errors() below as defense-in-depth, even
    though VacationRecord is frozen (domain/types.py) and __post_init__
    therefore now runs on every possible mutation
    (`dataclasses.replace()`), not just at initial construction.
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
        # This guard is what routes carry-over records to add_carry_over()
        # rather than the general debit/credit save path. It is load-bearing:
        # VacationRecord.__post_init__ deliberately does not reject
        # vtype=CARRY_OVER (carry-over rows inserted by add_carry_over() must
        # remain constructible so VacationModel._row_to_record() can read them
        # back without crashing the Vacation tab / export dialog), so a
        # carry-over record can legitimately reach this method and must be
        # rejected here.
        if record.vtype == VacationType.CARRY_OVER:
            return Result(
                ok=False,
                errors=("Use add_carry_over() to record carry-over hours.",),
            )

        invariant_errors = vacation_record_invariant_errors(record)
        if invariant_errors:
            return Result(ok=False, errors=tuple(invariant_errors))

        # The daily-target/summary/old-record reads and the insert/update are
        # all wrapped by the same guard below: a sqlite3.Error raised by any
        # of them (e.g. a locked DB during a read) must turn into a Result,
        # never propagate past this method.
        guard = DatabaseErrorGuard(
            logger, "Database error while saving vacation record %r", record
        )
        with guard:
            max_hours = self.model.get_daily_target_for_date(record.date)
            if max_hours == 0.0:
                max_hours = 8.0  # weekend/day-off: use 8h as reference cap

            errors = validate_vacation_record(record, max_hours)
            if errors:
                return Result(ok=False, errors=tuple(errors))

            # Check balance if this is a debit record (not carry-over or
            # unpaid leave)
            is_debit = record.vtype in _DEBIT_VACATION_TYPES

            # Non-blocking over-balance (a future flip of OVER_BALANCE.blocking)
            # must still surface on the success Result; carry it through here.
            over_balance_warnings: tuple[str, ...] = ()
            if is_debit:
                year = record.date.year
                summary = self.model.calculate_vacation_summary(year)

                # Balance impact is charge-weighted: a debit only spends
                # hours * charge_rate of the pool (a half-charged day costs
                # half its hours). If editing an existing same-year debit,
                # add back its old charge-weighted cost before subtracting
                # the new one to get the projected remaining.
                new_charge = record.hours * record.charge_rate
                old_charge = 0.0
                if record.id is not None:
                    old_rec = self.model.get_record_by_id(record.id)
                    if (
                        old_rec
                        and old_rec.vtype in _DEBIT_VACATION_TYPES
                        and old_rec.date.year == year
                    ):
                        old_charge = old_rec.hours * old_rec.charge_rate

                projected_remaining = summary.remaining + old_charge - new_charge

                if projected_remaining < 0:
                    # Hard block only when a borrow cap is configured and the
                    # overdraw exceeds it (WarningCode.OVER_BORROW_LIMIT — no
                    # confirm-then-retry). When max_borrow is 0 (the default)
                    # this branch is skipped entirely, so over-balance stays a
                    # confirm-then-retry exactly as before #47.
                    max_borrow = self.model.get_max_borrow_hours()
                    if max_borrow > 0 and projected_remaining < -max_borrow:
                        # Carry the structured WarningCode.OVER_BORROW_LIMIT
                        # alongside the user-facing message, mirroring how
                        # blocking codes (RECORD_NOT_FOUND, OVER_BALANCE) are
                        # surfaced in `errors` — the view keys off the code,
                        # not the free-text sentence.
                        return Result(
                            ok=False,
                            errors=(
                                WarningCode.OVER_BORROW_LIMIT.value,
                                f"Cannot borrow {(-projected_remaining):.1f} "
                                f"hours. Max borrow is {max_borrow:.1f} hours.",
                            ),
                        )
                    if not confirm_over_balance:
                        decision = over_balance_decision()
                        if not decision.ok:
                            return decision
                        over_balance_warnings = decision.warnings

            if record.id is None:
                record_id = self.model.insert_record(record)
                # Backfill the DB-generated id onto the frozen record.
                set_generated_id(record, record_id)
            else:
                self.model.update_record(record)
            return Result(ok=True, warnings=over_balance_warnings)
        return guard.unwrap()

    def add_carry_over(self, from_year: int, to_year: int, hours: float) -> Result:
        """Validates and records a carry-over allocation."""
        if hours <= 0:
            return Result(
                ok=False, errors=("Hours to transfer must be greater than zero.",)
            )

        guard = DatabaseErrorGuard(
            logger,
            "Database error while adding carry-over from_year=%s to_year=%s",
            from_year,
            to_year,
        )
        with guard:
            allowance = self.model.calculate_carry_over_allowance(to_year)
            allowed_max = allowance.allowed_transfer

            if hours > allowed_max:
                return Result(
                    ok=False,
                    errors=(
                        f"Cannot transfer {hours:.1f} hours. "
                        f"Max allowed is {allowed_max:.1f} hours.",
                    ),
                )

            self.model.add_carry_over(from_year, to_year, hours)
            return Result(ok=True, errors=())
        return guard.unwrap()

    def delete_record(self, record_id: int) -> Result:
        """Delete the vacation record with the given id."""
        guard = DatabaseErrorGuard(
            logger, "Database error while deleting vacation record id=%s", record_id
        )
        with guard:
            self.model.delete_record(record_id)
            return Result(ok=True, errors=())
        return guard.unwrap()

    def save_grant(self, grant: VacationGrant) -> Result:
        """Validates and saves a VacationGrant (insert if id is None, else
        update). Grants enlarge a year's pool via VacationSummary.extra_grant;
        they carry no over-balance check (adding hours never overdraws)."""
        invariant_errors = vacation_grant_invariant_errors(grant)
        if invariant_errors:
            return Result(ok=False, errors=tuple(invariant_errors))

        guard = DatabaseErrorGuard(
            logger, "Database error while saving vacation grant %r", grant
        )
        with guard:
            if grant.id is None:
                grant_id = self.model.insert_grant(grant)
                # Backfill the DB-generated id onto the frozen grant.
                set_generated_id(grant, grant_id)
            else:
                self.model.update_grant(grant)
            return Result(ok=True, errors=())
        return guard.unwrap()

    def delete_grant(self, grant_id: int) -> Result:
        """Delete the vacation grant with the given id."""
        guard = DatabaseErrorGuard(
            logger, "Database error while deleting vacation grant id=%s", grant_id
        )
        with guard:
            self.model.delete_grant(grant_id)
            return Result(ok=True, errors=())
        return guard.unwrap()
