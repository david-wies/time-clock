"""Miliuim controller: validates input and mediates model ↔ view."""

import logging

from controllers.time_clock_controller import DatabaseErrorGuard
from core.timeutil import to_display_date
from domain.types import (
    MiliuimRecord,
    Result,
    miliuim_record_invariant_errors,
    set_generated_id,
)
from models.miliuim_model import MiliuimModel

logger = logging.getLogger(__name__)


class MiliuimController:
    """MiliuimRecord validation is fully handled by static typing and
    MiliuimRecord.__post_init__; there is no free validate_miliuim_record()
    function, because every context-free check is either type-checked or
    lives in __post_init__. start_date/end_date being required is enforced by
    their type annotation (`date`, not `date | None`) rather than a runtime
    check — if a caller bypasses typing and
    passes None anyway, the `end_date < start_date` comparison in
    miliuim_record_invariant_errors() raises an unhandled TypeError.
    save_record() below catches that TypeError and converts it to a clean
    Result, per this codebase's "controllers return Result, never raise for
    expected validation failures" convention. end_date >= start_date and
    note length ARE runtime-checked, unconditionally, by
    MiliuimRecord.__post_init__. Only the overlap check remains here, since
    it needs other persisted records (context-dependent).

    MiliuimRecord is frozen (domain/types.py), so save_record() re-running
    miliuim_record_invariant_errors() below is no longer guarding against an
    in-place mutation bypassing __post_init__ — that path no longer exists
    (see MiliuimRecord's docstring). It remains as defense-in-depth against
    a record built or `dataclasses.replace()`-derived somewhere outside this
    module's control."""

    def __init__(self, model: MiliuimModel) -> None:
        self.model = model

    def save_record(self, record: MiliuimRecord) -> Result:
        """Validates and saves (inserts or updates) a MiliuimRecord."""
        try:
            errors: list[str] = miliuim_record_invariant_errors(record)
        except TypeError:
            # start_date/end_date are required, non-Optional fields on
            # MiliuimRecord, but a caller can still bypass static typing
            # (e.g. a dynamically constructed record) and hand this method
            # one with a None date, which makes the `end_date < start_date`
            # comparison inside miliuim_record_invariant_errors() raise
            # TypeError instead of producing a clean validation error.
            # Log with a traceback (matching the logger.exception() that
            # DatabaseErrorGuard emits for the sqlite3 errors guarded below)
            # before converting to a Result, so this typing-bypass leaves an
            # audit trail.
            logger.exception(
                "Invalid Miliuim record: start_date/end_date comparison raised "
                "TypeError (a required date field was None) for record %r",
                record,
            )
            return Result(ok=False, errors=("Start date and end date are required.",))
        if errors:
            return Result(ok=False, errors=tuple(errors))

        # The overlap-check read and the insert/update are both wrapped by
        # the same guard below: a sqlite3.Error raised by either one (e.g.
        # a locked DB during the read) must turn into a Result, never
        # propagate past this method.
        guard = DatabaseErrorGuard(
            logger, "Database error while saving Miliuim record %r", record
        )
        with guard:
            # Uses a lightweight raw-SQL read (id, start_date, end_date only)
            # instead of get_records_in_date_range(), which goes through
            # MiliuimRecord construction and silently drops any row that
            # fails validation (see MiliuimModel._row_to_record()). A
            # dropped row here would make a genuinely overlapping period
            # invisible to this check and let it be saved anyway.
            existing_ranges = self.model.get_date_ranges_in_range(
                record.start_date, record.end_date
            )
            for other_id, other_start, other_end in existing_ranges:
                if other_id == record.id:
                    continue
                other_start_str = to_display_date(other_start)
                other_end_str = to_display_date(other_end)
                return Result(
                    ok=False,
                    errors=(
                        "Period overlaps with an existing Miliuim period "
                        f"({other_start_str} – {other_end_str}).",
                    ),
                )

            if record.id is None:
                record_id = self.model.insert_record(record)
                # Backfill the DB-generated id onto the frozen record.
                set_generated_id(record, record_id)
            else:
                self.model.update_record(record)
            return Result(ok=True, errors=())
        return guard.unwrap()

    def delete_record(self, record_id: int) -> Result:
        """Delete the Miliuim record with the given id."""
        guard = DatabaseErrorGuard(
            logger, "Database error while deleting Miliuim record id=%s", record_id
        )
        with guard:
            self.model.delete_record(record_id)
            return Result(ok=True, errors=())
        return guard.unwrap()
