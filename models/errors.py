"""Model-layer exceptions."""

import sqlite3
from typing import Literal

Entity = Literal["time_record", "vacation_record", "sickness_record", "miliuim_record"]


class RecordNotFoundError(Exception):
    """Raised by update_record()/delete_record() when cursor.rowcount == 0
    — the record was already deleted (e.g. a double-click delete or stale
    UI state race), not a genuine DB connectivity/query failure.

    Deliberately does NOT subclass sqlite3.Error (or any of its
    subclasses): this is enforced by the type system, not by branch
    ordering, so a bare `except sqlite3.Error` elsewhere in the codebase
    will NOT catch it and silently conflate a "record already gone" race
    with a real database failure. Callers that need to handle this case —
    currently only `DatabaseErrorGuard` in
    controllers/time_clock_controller.py — must catch it explicitly.
    """

    def __init__(self, entity: Entity, record_id: int, action: str) -> None:
        self._entity: Entity = entity
        self._record_id: int = record_id
        self._action: str = action
        super().__init__(f"No {entity} with id={record_id} exists to {action}")

    @property
    def entity(self) -> Entity:
        """The kind of record that was not found (read-only after construction —
        see class docstring for why this must be trustworthy diagnostic data)."""
        return self._entity

    @property
    def record_id(self) -> int:
        """The id of the record that was not found (read-only after construction)."""
        return self._record_id

    @property
    def action(self) -> str:
        """The action that was attempted (e.g. "update", "delete") (read-only
        after construction)."""
        return self._action


def raise_if_no_rows(
    cursor: sqlite3.Cursor, entity: Entity, record_id: int, action: str
) -> None:
    """Raises RecordNotFoundError if `cursor`'s last statement affected zero
    rows. Call this immediately after an UPDATE/DELETE in update_record()/
    delete_record() to centralize the rowcount-based staleness check.
    """
    if cursor.rowcount == 0:
        raise RecordNotFoundError(entity, record_id, action)
