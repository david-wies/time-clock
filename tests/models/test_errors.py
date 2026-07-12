import pickle
import sqlite3

import pytest

from domain.enums import RecordAction, RecordEntity
from models.errors import RecordNotFoundError, raise_if_no_rows


@pytest.fixture
def cursor() -> sqlite3.Cursor:
    """A real sqlite3 cursor against a throwaway in-memory table, so
    cursor.rowcount reflects an actual UPDATE/DELETE outcome rather than a
    mocked attribute."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE dummy (id INTEGER PRIMARY KEY)")
    conn.execute("INSERT INTO dummy (id) VALUES (1)")
    conn.commit()
    return conn.cursor()


def test_raise_if_no_rows_does_not_raise_when_rows_affected(
    cursor: sqlite3.Cursor,
) -> None:
    """A real DELETE that hits an existing row sets cursor.rowcount == 1, so
    raise_if_no_rows() must be a no-op."""
    cursor.execute("DELETE FROM dummy WHERE id = 1")

    raise_if_no_rows(cursor, RecordEntity.TIME_RECORD, 1, RecordAction.DELETE)


def test_raise_if_no_rows_raises_when_no_rows_affected(cursor: sqlite3.Cursor) -> None:
    """A real DELETE against a nonexistent id sets cursor.rowcount == 0, so
    raise_if_no_rows() must raise RecordNotFoundError."""
    cursor.execute("DELETE FROM dummy WHERE id = 999999")

    with pytest.raises(RecordNotFoundError):
        raise_if_no_rows(cursor, RecordEntity.TIME_RECORD, 999999, RecordAction.DELETE)


def test_record_not_found_error_message_format() -> None:
    """The message must be exactly f"No {entity} with id={record_id} exists
    to {action}" — pinned here in isolation from the 8 model call sites."""
    err = RecordNotFoundError(RecordEntity.VACATION_RECORD, 42, RecordAction.UPDATE)

    assert str(err) == "No vacation_record with id=42 exists to update"


def test_record_not_found_error_sets_attributes() -> None:
    """entity, record_id, and action must be stored verbatim as attributes
    for callers that need to inspect them (e.g. DatabaseErrorGuard)."""
    err = RecordNotFoundError(RecordEntity.SICKNESS_RECORD, 7, RecordAction.DELETE)

    assert err.entity == RecordEntity.SICKNESS_RECORD
    assert err.record_id == 7
    assert err.action == RecordAction.DELETE


def test_record_not_found_error_is_not_a_sqlite3_error() -> None:
    """Regression guard: RecordNotFoundError must NOT subclass sqlite3.Error
    (or any of its subclasses). If a future change re-introduces subclassing
    sqlite3.DatabaseError, a bare `except sqlite3.Error` elsewhere in the
    codebase would silently swallow a "record already gone" race as if it
    were a real database failure."""
    err = RecordNotFoundError(RecordEntity.MILIUIM_RECORD, 1, RecordAction.UPDATE)

    assert not isinstance(err, sqlite3.Error)


def test_record_not_found_error_rejects_invalid_entity() -> None:
    """entity is now a RecordEntity enum, but the model modules that call
    this constructor are excluded from strict mypy checking, so the runtime
    guard in __init__ must still reject anything that isn't a RecordEntity
    member (e.g. a plain string) rather than flow into diagnostic logs."""
    with pytest.raises(ValueError, match="Invalid entity"):
        RecordNotFoundError("bogus_entity", 1, RecordAction.UPDATE)  # type: ignore[arg-type]


def test_record_not_found_error_rejects_invalid_action() -> None:
    """Same runtime guard as for entity: an action that isn't a RecordAction
    member must raise ValueError rather than flow into diagnostic logs."""
    with pytest.raises(ValueError, match="Invalid action"):
        RecordNotFoundError(RecordEntity.TIME_RECORD, 1, "insert")  # type: ignore[arg-type]


def test_record_not_found_error_is_immutable() -> None:
    """entity/record_id/action must be structurally immutable after
    construction — DatabaseErrorGuard logs them verbatim, so a mutated
    value would produce a misleading diagnostic log line. Underscore-prefixed
    fields with read-only @property alone don't prevent `err._entity = ...`;
    __setattr__/__delattr__ must block it outright."""
    err = RecordNotFoundError(RecordEntity.TIME_RECORD, 1, RecordAction.UPDATE)

    with pytest.raises(AttributeError):
        err._entity = RecordEntity.VACATION_RECORD  # type: ignore[misc]
    with pytest.raises(AttributeError):
        err.record_id = 2  # type: ignore[misc, assignment]
    with pytest.raises(AttributeError):
        del err._entity  # type: ignore[misc]


def test_raise_if_no_rows_raises_runtime_error_after_select(
    cursor: sqlite3.Cursor,
) -> None:
    """After a real SELECT, sqlite3 leaves cursor.rowcount == -1 (unavailable).
    raise_if_no_rows() must raise RuntimeError there instead of silently
    passing, which would mask a misplaced call."""
    cursor.execute("SELECT id FROM dummy")

    with pytest.raises(RuntimeError, match="rowcount is unavailable"):
        raise_if_no_rows(cursor, RecordEntity.TIME_RECORD, 1, RecordAction.UPDATE)


def test_record_not_found_error_pickle_round_trip() -> None:
    """Exception's default __reduce__ replays self.args (the single formatted
    message) into the three-argument __init__, so unpickling would raise
    TypeError without the __reduce__ override — pin the round-trip here."""
    err = RecordNotFoundError(RecordEntity.VACATION_RECORD, 42, RecordAction.DELETE)

    # Safe: round-tripping bytes we just produced in-process, not loading
    # pickle data from an external source.
    restored = pickle.loads(pickle.dumps(err))

    assert restored.entity == RecordEntity.VACATION_RECORD
    assert restored.record_id == 42
    assert restored.action == RecordAction.DELETE
    assert str(restored) == str(err)
