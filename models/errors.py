"""Model-layer exceptions."""

import sqlite3

from domain.enums import RecordAction, RecordEntity


class RecordNotFoundError(Exception):
    """Raised by update_record()/delete_record() when cursor.rowcount == 0
    — the record was already deleted (e.g. a double-click delete or stale
    UI state race), not a genuine DB connectivity/query failure.

    Deliberately does NOT subclass sqlite3.Error (or any of its
    subclasses): a bare `except sqlite3.Error` elsewhere in the codebase
    must NOT catch it and silently conflate a "record already gone" race
    with a real database failure. Callers that need to handle this case —
    currently only `DatabaseErrorGuard` in
    controllers/time_clock_controller.py — must catch it explicitly.
    """

    def __init__(
        self, entity: RecordEntity, record_id: int, action: RecordAction
    ) -> None:
        # Runtime guards: mypy never checks the model call sites (models/*
        # other than this file are excluded from strict checking), so a
        # wrong type would otherwise flow straight into diagnostic logs.
        if not isinstance(entity, RecordEntity):
            raise ValueError(f"Invalid entity {entity!r}: must be a RecordEntity")
        if not isinstance(action, RecordAction):
            raise ValueError(f"Invalid action {action!r}: must be a RecordAction")
        if isinstance(record_id, bool) or not isinstance(record_id, int):
            raise ValueError(f"Invalid record_id {record_id!r}: must be an int")
        self.entity = entity
        self.record_id = record_id
        self.action = action
        super().__init__(f"No {entity} with id={record_id} exists to {action}")


def raise_if_no_rows(
    cursor: sqlite3.Cursor,
    entity: RecordEntity,
    record_id: int,
    action: RecordAction,
) -> None:
    """Raises RecordNotFoundError if `cursor`'s last statement affected zero
    rows. Call this immediately after an UPDATE/DELETE in update_record()/
    delete_record() to centralize the rowcount-based staleness check.

    Raises RuntimeError if rowcount is unavailable (-1) — e.g. after a
    SELECT or on a fresh cursor — since silently passing there would mask
    a misplaced call.
    """
    if cursor.rowcount < 0:
        raise RuntimeError(
            "raise_if_no_rows called where rowcount is unavailable "
            "(rowcount == -1) — call it immediately after an UPDATE/DELETE"
        )
    if cursor.rowcount == 0:
        raise RecordNotFoundError(entity, record_id, action)
