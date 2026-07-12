"""Model-layer exceptions."""

import sqlite3
from typing import Any

from domain.enums import RecordAction, RecordEntity


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

    Immutable after construction: `__setattr__`/`__delattr__` are
    overridden to always raise, so `err._entity = ...` is structurally
    blocked rather than merely discouraged by a leading underscore —
    DatabaseErrorGuard logs `entity`/`action` verbatim, so a mutated value
    would produce a misleading diagnostic log line. `__init__` bypasses
    the override via `object.__setattr__` to do the one legitimate set.
    """

    _entity: RecordEntity
    _record_id: int
    _action: RecordAction

    # The only attributes this type's own construction protocol owns and
    # freezes. Everything else (notably __traceback__, __context__,
    # __cause__, __suppress_context__, __notes__) is set on an exception
    # instance by the interpreter itself as it propagates/is re-raised —
    # __setattr__/__delattr__ below must let those through untouched, or
    # a plain `raise` of this exception would blow up trying to attach a
    # traceback to it.
    _FROZEN_FIELDS = frozenset({"_entity", "_record_id", "_action"})

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
        # Bypasses __setattr__ below, which would otherwise reject these
        # names as frozen.
        object.__setattr__(self, "_entity", entity)
        object.__setattr__(self, "_record_id", record_id)
        object.__setattr__(self, "_action", action)
        super().__init__(f"No {entity} with id={record_id} exists to {action}")

    def __setattr__(self, name: str, value: Any) -> None:
        if name in RecordNotFoundError._FROZEN_FIELDS:
            raise AttributeError(
                f"{type(self).__name__} is immutable: cannot set {name!r}"
            )
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        if name in RecordNotFoundError._FROZEN_FIELDS:
            raise AttributeError(
                f"{type(self).__name__} is immutable: cannot delete {name!r}"
            )
        object.__delattr__(self, name)

    def __reduce__(
        self,
    ) -> tuple[type[RecordNotFoundError], tuple[RecordEntity, int, RecordAction]]:
        # Exception's default __reduce__ replays self.args — here the single
        # formatted message — into __init__, which takes three arguments, so
        # unpickling would raise TypeError without this override.
        return (type(self), (self._entity, self._record_id, self._action))

    @property
    def entity(self) -> RecordEntity:
        """The kind of record that was not found (read-only after construction —
        DatabaseErrorGuard logs it verbatim, so a mutated value would produce a
        misleading diagnostic log line)."""
        return self._entity

    @property
    def record_id(self) -> int:
        """The id of the record that was not found (read-only after construction)."""
        return self._record_id

    @property
    def action(self) -> RecordAction:
        """The action that was attempted ("update" or "delete") (read-only
        after construction)."""
        return self._action


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
