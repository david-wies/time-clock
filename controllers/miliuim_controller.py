import logging

from controllers.time_clock_controller import DatabaseErrorGuard
from domain.types import MiliuimRecord, Result, miliuim_record_invariant_errors
from models.miliuim_model import MiliuimModel

logger = logging.getLogger(__name__)


class MiliuimController:
    """Note: there is no free validate_miliuim_record() function anymore —
    every check it used to perform (start/end date required, end >= start,
    note length) was context-free and is now enforced unconditionally by
    MiliuimRecord.__post_init__. Only the overlap check remains here, since
    it needs other persisted records (context-dependent).

    save_record() re-runs miliuim_record_invariant_errors() below because
    __post_init__ only fires at construction time — a caller that fetches
    an existing record and mutates a field (e.g. record.end_date = ...)
    before calling save_record() would otherwise bypass those invariants
    entirely."""

    def __init__(self, model: MiliuimModel) -> None:
        self.model = model

    def save_record(self, record: MiliuimRecord) -> Result:
        errors: list[str] = miliuim_record_invariant_errors(record)
        if errors:
            return Result(ok=False, errors=errors)

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
                return Result(
                    ok=False,
                    errors=[
                        "Period overlaps with an existing Miliuim period "
                        f"({other_start.isoformat()} – {other_end.isoformat()})."
                    ],
                )

            if record.id is None:
                record_id = self.model.insert_record(record)
                record.id = record_id
            else:
                self.model.update_record(record)
            return Result(ok=True, errors=[])
        assert guard.result is not None
        return guard.result

    def delete_record(self, record_id: int) -> Result:
        guard = DatabaseErrorGuard(
            logger, "Database error while deleting Miliuim record id=%s", record_id
        )
        with guard:
            self.model.delete_record(record_id)
            return Result(ok=True, errors=[])
        assert guard.result is not None
        return guard.result
