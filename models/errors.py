"""Model-layer exceptions."""

import sqlite3


class RecordNotFoundError(sqlite3.DatabaseError):
    """Raised by update_record()/delete_record() when cursor.rowcount == 0
    — the record was already deleted (e.g. a double-click delete or stale
    UI state race), not a genuine DB connectivity/query failure.

    Subclasses sqlite3.DatabaseError (not a fresh Exception subclass) so
    existing `except sqlite3.Error` call sites keep working unchanged;
    only DatabaseErrorGuard in controllers/time_clock_controller.py needs
    to special-case it for a clearer user-facing message.
    """

    def __init__(self, entity: str, record_id: int, action: str) -> None:
        self.entity = entity
        self.record_id = record_id
        self.action = action
        super().__init__(f"No {entity} with id={record_id} exists to {action}")


def raise_if_no_rows(
    cursor: sqlite3.Cursor, entity: str, record_id: int, action: str
) -> None:
    """Raises RecordNotFoundError if `cursor`'s last statement affected zero
    rows. Call this immediately after an UPDATE/DELETE in update_record()/
    delete_record() to centralize the rowcount-based staleness check.
    """
    if cursor.rowcount == 0:
        raise RecordNotFoundError(entity, record_id, action)
