"""Tests for db/database.py connection lifecycle and schema.

Covers the connection-reuse fix: ``Database`` now opens a single,
persistent connection at construction time for *both* file-based and
``:memory:`` databases (previously only ``:memory:`` got a shared
connection — file-based DBs re-opened + re-configured a brand new
``sqlite3.Connection`` on every ``get_connection()`` call). The existing
``~40`` `conn = self.db.get_connection(); try: ...; finally: conn.close()`
call sites across ``models/*.py`` are unchanged by this fix — for both
DB kinds, ``.close()`` is now a safe no-op (see ``SharedConnectionWrapper``),
so nothing at those call sites needs to change.
"""
import sqlite3

from db.database import Database, SharedConnectionWrapper


def test_get_connection_returns_shared_wrapper_for_file_db(tmp_path) -> None:
    """Previously only ``:memory:`` DBs got a SharedConnectionWrapper; a
    file-based DB got a brand new sqlite3.Connection per call."""
    db_path = tmp_path / "time_clock.db"
    db = Database(db_path=str(db_path))
    conn = db.get_connection()
    assert isinstance(conn, SharedConnectionWrapper)


def test_get_connection_returns_same_object_across_calls_file_db(tmp_path) -> None:
    """The whole point of the fix: repeated get_connection() calls on a
    file-based DB must return the identical object, not a fresh connection
    each time (previously: brand new sqlite3.connect() + PRAGMA replay on
    every single call)."""
    db_path = tmp_path / "time_clock.db"
    db = Database(db_path=str(db_path))
    conn1 = db.get_connection()
    conn2 = db.get_connection()
    conn3 = db.get_connection()
    assert conn1 is conn2 is conn3


def test_get_connection_returns_same_object_across_calls_memory_db() -> None:
    """Pre-existing :memory: behavior must be unchanged by this fix."""
    db = Database(db_path=":memory:")
    conn1 = db.get_connection()
    conn2 = db.get_connection()
    assert conn1 is conn2


def test_shared_connection_close_is_a_no_op_for_file_db(tmp_path) -> None:
    """The ~40 `finally: conn.close()` call sites in models/*.py must
    become harmless no-ops for file-based DBs too, exactly as they already
    are for :memory: — this is what lets the next cleanup task treat both
    DB kinds identically without touching those call sites."""
    db_path = tmp_path / "time_clock.db"
    db = Database(db_path=str(db_path))
    conn = db.get_connection()
    conn.close()
    # Connection must still be usable after "close" — proving it never
    # actually closed the underlying sqlite3.Connection.
    conn.execute("SELECT 1;")
    conn2 = db.get_connection()
    assert conn2 is conn


def test_pragmas_configured_once_at_construction_for_file_db(tmp_path) -> None:
    """journal_mode=WAL, foreign_keys=ON, and the previously-missing
    synchronous=NORMAL must all be set on the persistent connection."""
    db_path = tmp_path / "time_clock.db"
    db = Database(db_path=str(db_path))
    conn = db.get_connection()

    journal_mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
    assert journal_mode.lower() == "wal"

    foreign_keys = conn.execute("PRAGMA foreign_keys;").fetchone()[0]
    assert foreign_keys == 1

    synchronous = conn.execute("PRAGMA synchronous;").fetchone()[0]
    # NORMAL == 1 in SQLite's PRAGMA synchronous encoding.
    assert synchronous == 1


def test_pragmas_configured_for_memory_db() -> None:
    """foreign_keys and synchronous should also be set for :memory: DBs;
    journal_mode is reported as 'memory' regardless of the WAL pragma."""
    db = Database(db_path=":memory:")
    conn = db.get_connection()

    foreign_keys = conn.execute("PRAGMA foreign_keys;").fetchone()[0]
    assert foreign_keys == 1

    synchronous = conn.execute("PRAGMA synchronous;").fetchone()[0]
    assert synchronous == 1


def test_row_factory_is_sqlite3_row_for_file_db(tmp_path) -> None:
    db_path = tmp_path / "time_clock.db"
    db = Database(db_path=str(db_path))
    conn = db.get_connection()
    assert conn.row_factory is sqlite3.Row


def test_wrapper_attribute_write_does_not_leak_onto_wrapped_connection(tmp_path) -> None:
    """SharedConnectionWrapper.__setattr__ was narrowed to plain (default)
    attribute assignment: writes must land on the wrapper instance itself,
    not silently forward onto the wrapped sqlite3.Connection, so future
    wrapper-owned state can't accidentally corrupt connection state."""
    db_path = tmp_path / "time_clock.db"
    db = Database(db_path=str(db_path))
    conn = db.get_connection()

    conn.some_wrapper_only_attr = "wrapper-owned"

    assert conn.some_wrapper_only_attr == "wrapper-owned"
    # The underlying real sqlite3.Connection must be untouched.
    assert not hasattr(conn._conn, "some_wrapper_only_attr")


def test_wrapper_attribute_read_still_forwards_to_wrapped_connection(tmp_path) -> None:
    """Reads for attributes the wrapper doesn't itself define (e.g.
    ``row_factory``) must still forward to the wrapped connection via
    ``__getattr__`` — only writes were narrowed, not reads."""
    db_path = tmp_path / "time_clock.db"
    db = Database(db_path=str(db_path))
    conn = db.get_connection()
    assert conn.row_factory is conn._conn.row_factory is sqlite3.Row


def test_repeated_model_style_usage_does_not_reopen_connection(tmp_path) -> None:
    """Regression test mirroring the ~40 `models/*.py` call sites:
    `conn = db.get_connection(); try: ...; finally: conn.close()` repeated
    many times must keep operating on the same underlying connection."""
    db_path = tmp_path / "time_clock.db"
    db = Database(db_path=str(db_path))

    seen_ids = set()
    for _ in range(5):
        conn = db.get_connection()
        try:
            seen_ids.add(id(conn))
        finally:
            conn.close()

    assert len(seen_ids) == 1


# ─────────────────────── Missing index (open-records query) ────────────────

def test_time_record_open_index_exists(tmp_path) -> None:
    """`WHERE end_time IS NULL` queries (get_open_records() and ~5 other
    call sites, including the 60s auto-refresh timer) must be backed by a
    partial index instead of a full table scan."""
    db_path = tmp_path / "time_clock.db"
    db = Database(db_path=str(db_path))
    conn = db.get_connection()
    rows = conn.execute(
        "SELECT name, sql FROM sqlite_master "
        "WHERE type = 'index' AND tbl_name = 'time_record' "
        "AND name = 'idx_time_record_open';"
    ).fetchall()
    assert len(rows) == 1
    sql = rows[0]["sql"]
    assert "end_time" in sql
    assert "IS NULL" in sql


def test_time_record_open_index_present_on_migrated_existing_db(tmp_path) -> None:
    """Existing installed DBs (created before this change, at an older
    `PRAGMA user_version`) must pick up the new index on next startup —
    not just brand-new databases going through `_create_tables`."""
    db_path = tmp_path / "time_clock.db"

    # Simulate a pre-existing DB at schema version 7 (the version at HEAD
    # before this task), with no idx_time_record_open index.
    raw = sqlite3.connect(str(db_path))
    raw.execute("PRAGMA foreign_keys=ON;")
    raw.execute("""
        CREATE TABLE time_record (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            date          TEXT    NOT NULL,
            start_time    TEXT    NOT NULL,
            end_time      TEXT    DEFAULT NULL,
            break_minutes INTEGER NOT NULL DEFAULT 0,
            work_type     TEXT    NOT NULL CHECK(work_type IN ('in_site', 'road', 'remote')),
            office        TEXT,
            note          TEXT,
            document_path TEXT,
            created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
            updated_at    TEXT    NOT NULL DEFAULT (datetime('now'))
        );
    """)
    raw.execute("PRAGMA user_version = 7;")
    raw.commit()
    raw.close()

    # Now open it through Database — the migration path (not _create_tables,
    # since the table already exists) must add the index.
    db = Database(db_path=str(db_path))
    conn = db.get_connection()
    rows = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type = 'index' AND tbl_name = 'time_record' "
        "AND name = 'idx_time_record_open';"
    ).fetchall()
    assert len(rows) == 1
