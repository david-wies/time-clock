"""Model-layer exceptions."""

import sqlite3
from typing import Literal, get_args

Entity = Literal["time_record", "vacation_record", "sickness_record", "miliuim_record"]
Action = Literal["update", "delete"]


class RecordNotFoundError(Exception):
    """Raised by update_record()/delete_record() when cursor.rowcount == 0
    — the record was already deleted (e.g. a double-click delete or stale
    UI state race), not a genuine DB connectivity/query failure.

    Deliberately does NOT subclass sqlite3.Error (or any of its
    subclasses): the disjointness is enforced by the exception hierarchy
    at runtime and pinned by the regression test
    test_record_not_found_error_is_not_a_sqlite3_error, so a bare
    `except sqlite3.Error` elsewhere in the codebase will NOT catch it
    and silently conflate a "record already gone" race with a real
    database failure. Callers that need to handle this case — currently
    only `DatabaseErrorGuard` in controllers/time_clock_controller.py —
    must catch it explicitly.
    """

    def __init__(self, entity: Entity, record_id: int, action: Action) -> None:
        # Runtime guards: mypy never checks the model call sites (models/*
        # other than this file are excluded from strict checking), so bad
        # literals would otherwise flow straight into diagnostic logs.
        if entity not in get_args(Entity):
            raise ValueError(
                f"Invalid entity {entity!r}: must be one of {get_args(Entity)}"
            )
        if action not in get_args(Action):
            raise ValueError(
                f"Invalid action {action!r}: must be one of {get_args(Action)}"
            )
        self._entity: Entity = entity
        self._record_id: int = record_id
        self._action: Action = action
        super().__init__(f"No {entity} with id={record_id} exists to {action}")

    def __reduce__(
        self,
    ) -> tuple[type[RecordNotFoundError], tuple[Entity, int, Action]]:
        # Exception's default __reduce__ replays self.args — here the single
        # formatted message — into __init__, which takes three arguments, so
        # unpickling would raise TypeError without this override.
        return (type(self), (self._entity, self._record_id, self._action))

    @property
    def entity(self) -> Entity:
        """The kind of record that was not found (read-only after construction —
        DatabaseErrorGuard logs it verbatim, so a mutated value would produce a
        misleading diagnostic log line)."""
        return self._entity

    @property
    def record_id(self) -> int:
        """The id of the record that was not found (read-only after construction)."""
        return self._record_id

    @property
    def action(self) -> Action:
        """The action that was attempted ("update" or "delete") (read-only
        after construction)."""
        return self._action


def raise_if_no_rows(
    cursor: sqlite3.Cursor, entity: Entity, record_id: int, action: Action
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
