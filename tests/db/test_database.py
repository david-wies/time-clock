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

import logging
import sqlite3

import pytest

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
    """journal_mode=WAL, foreign_keys=ON, and synchronous=FULL must all be
    set on the persistent connection. FULL (not NORMAL) is required for
    file-backed DBs: with WAL mode, synchronous=NORMAL can lose a committed
    transaction on OS crash or power loss, which is unacceptable for this
    app's time-tracking/payroll-adjacent data."""
    db_path = tmp_path / "time_clock.db"
    db = Database(db_path=str(db_path))
    conn = db.get_connection()

    journal_mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
    assert journal_mode.lower() == "wal"

    foreign_keys = conn.execute("PRAGMA foreign_keys;").fetchone()[0]
    assert foreign_keys == 1

    synchronous = conn.execute("PRAGMA synchronous;").fetchone()[0]
    # FULL == 2 in SQLite's PRAGMA synchronous encoding.
    assert synchronous == 2


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


def test_wrapper_attribute_write_does_not_leak_onto_wrapped_connection(
    tmp_path,
) -> None:
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
            work_type     TEXT    NOT NULL
                CHECK(work_type IN ('in_site', 'road', 'remote')),
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


# ─────────────── Data-preserving migrations (versions 2 and 3) ──────────────
#
# Both migrations rebuild a table (CREATE new-named table, INSERT OR IGNORE
# ... SELECT * FROM old, DROP old, RENAME new -> old). "INSERT OR IGNORE"
# silently *drops* any row that would violate the new table's CHECK
# constraints instead of raising — so a regression in either migration could
# quietly lose or corrupt pre-existing rows without any visible error. These
# tests build a raw pre-migration database by hand (mirroring the pattern in
# test_time_record_open_index_present_on_migrated_existing_db above),
# populate it with real rows, then open it through Database (triggering the
# migration path) and verify every row survived intact.


def test_vacation_record_v2_migration_preserves_existing_rows(tmp_path) -> None:
    """version 1 schema has CHECK(hours > 0) on vacation_record; version 2
    relaxes it to CHECK(hours >= 0) via a full table rebuild. Pre-existing
    rows (which, under the OLD schema, could only ever have hours > 0) must
    survive the rebuild with their data intact, and the relaxation itself
    must actually take effect afterwards (a fresh hours=0 insert must
    succeed post-migration, proving the rebuilt table really carries the
    relaxed constraint rather than silently keeping the old one)."""
    db_path = tmp_path / "time_clock.db"

    raw = sqlite3.connect(str(db_path))
    raw.execute("PRAGMA foreign_keys=ON;")
    raw.execute("""
        CREATE TABLE vacation_record (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            date        TEXT    NOT NULL,
            hours       REAL    NOT NULL CHECK(hours > 0),
            vtype       TEXT    NOT NULL
                CHECK(vtype IN ('annual_leave', 'public_holiday',
                    'unpaid_leave', 'special_leave', 'carry_over')),
            note        TEXT,
            created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
            updated_at  TEXT    NOT NULL DEFAULT (datetime('now'))
        );
    """)
    # Sanity check on the hand-built fixture: the OLD schema really is
    # stricter than the relaxed one — an hours=0 row cannot exist under it.
    with pytest.raises(sqlite3.IntegrityError):
        raw.execute(
            "INSERT INTO vacation_record (date, hours, vtype) "
            "VALUES ('2026-02-01', 0.0, 'public_holiday');"
        )

    raw.execute(
        "INSERT INTO vacation_record (date, hours, vtype, note) VALUES "
        "('2026-01-05', 8.0, 'annual_leave', 'first row'),"
        "('2026-01-06', 0.5, 'special_leave', 'second row'),"
        "('2026-01-07', 4.25, 'unpaid_leave', NULL);"
    )
    raw.execute("PRAGMA user_version = 1;")
    raw.commit()
    raw.close()

    db = Database(db_path=str(db_path))
    conn = db.get_connection()

    rows = conn.execute(
        "SELECT date, hours, vtype, note FROM vacation_record ORDER BY date;"
    ).fetchall()
    assert len(rows) == 3
    assert rows[0]["date"] == "2026-01-05"
    assert rows[0]["hours"] == 8.0
    assert rows[0]["vtype"] == "annual_leave"
    assert rows[0]["note"] == "first row"
    assert rows[1]["hours"] == 0.5
    assert rows[2]["hours"] == 4.25
    assert rows[2]["note"] is None

    # The relaxation must actually be live on the rebuilt table now.
    conn.execute(
        "INSERT INTO vacation_record (date, hours, vtype) "
        "VALUES ('2026-02-01', 0.0, 'public_holiday');"
    )
    count = conn.execute("SELECT COUNT(*) FROM vacation_record;").fetchone()[0]
    assert count == 4

    user_version = conn.execute("PRAGMA user_version;").fetchone()[0]
    assert user_version == 8


def test_sickness_settings_v3_migration_converts_days_to_hours_and_preserves_rows(
    tmp_path,
) -> None:
    """version 3 rebuilds sickness_settings from a days_per_year column to
    hours_per_year (days_per_year * 8.0). A regression here could corrupt
    the conversion math or drop rows during the rebuild."""
    db_path = tmp_path / "time_clock.db"

    raw = sqlite3.connect(str(db_path))
    raw.execute("PRAGMA foreign_keys=ON;")
    raw.execute("""
        CREATE TABLE sickness_settings (
            year             INTEGER PRIMARY KEY,
            days_per_year    REAL NOT NULL CHECK(days_per_year >= 0)
        );
    """)
    raw.execute(
        "INSERT INTO sickness_settings (year, days_per_year) VALUES "
        "(2025, 12.5), (2026, 18.0);"
    )
    raw.execute("PRAGMA user_version = 2;")
    raw.commit()
    raw.close()

    db = Database(db_path=str(db_path))
    conn = db.get_connection()

    rows = conn.execute(
        "SELECT year, hours_per_year FROM sickness_settings ORDER BY year;"
    ).fetchall()
    assert len(rows) == 2
    assert rows[0]["year"] == 2025
    assert rows[0]["hours_per_year"] == pytest.approx(12.5 * 8.0)
    assert rows[1]["year"] == 2026
    assert rows[1]["hours_per_year"] == pytest.approx(18.0 * 8.0)

    user_version = conn.execute("PRAGMA user_version;").fetchone()[0]
    assert user_version == 8


def test_time_record_v8_migration_repairs_negative_break_minutes_and_logs_warning(
    tmp_path, caplog
) -> None:
    """A pre-existing row with a corrupt negative break_minutes value (e.g.
    from manual DB editing, predating this constraint) must NOT be silently
    dropped by the v8 rebuild's `INSERT OR IGNORE` — CHECK-constraint
    violations are skipped per-row rather than raised, so an unrepaired bad
    row would simply vanish with no trace. The migration must instead clamp
    the value to 0, log a WARNING identifying the row, and keep the row."""
    db_path = tmp_path / "time_clock.db"

    raw = sqlite3.connect(str(db_path))
    raw.execute("PRAGMA foreign_keys=ON;")
    raw.execute("""
        CREATE TABLE time_record (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            date          TEXT    NOT NULL,
            start_time    TEXT    NOT NULL,
            end_time      TEXT    DEFAULT NULL,
            break_minutes INTEGER NOT NULL DEFAULT 0,
            work_type     TEXT    NOT NULL
                CHECK(work_type IN ('in_site', 'road', 'remote')),
            office        TEXT,
            note          TEXT,
            created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
            updated_at    TEXT    NOT NULL DEFAULT (datetime('now')),
            document_path TEXT
        );
    """)
    raw.execute(
        "INSERT INTO time_record (date, start_time, break_minutes, work_type, note) "
        "VALUES ('2026-01-05', '09:00', -15, 'in_site', 'corrupted row'),"
        "('2026-01-06', '10:00', 20, 'remote', 'healthy row');"
    )
    raw.execute("PRAGMA user_version = 7;")
    raw.commit()
    raw.close()

    with caplog.at_level(logging.WARNING, logger="db.database"):
        db = Database(db_path=str(db_path))
    conn = db.get_connection()

    rows = conn.execute(
        "SELECT date, break_minutes, note FROM time_record ORDER BY date;"
    ).fetchall()
    # Both rows survive the rebuild -- the corrupted row is repaired, not
    # dropped.
    assert len(rows) == 2
    assert rows[0]["date"] == "2026-01-05"
    assert rows[0]["break_minutes"] == 0
    assert rows[0]["note"] == "corrupted row"
    assert rows[1]["break_minutes"] == 20

    assert any(
        record.levelname == "WARNING"
        and "break_minutes" in record.message.lower()
        and "2026-01-05" in record.message
        for record in caplog.records
    )

    user_version = conn.execute("PRAGMA user_version;").fetchone()[0]
    assert user_version == 8


def test_time_record_v8_migration_preserves_rows_and_adds_break_minutes_check(
    tmp_path,
) -> None:
    """version 8 rebuilds time_record to add CHECK(break_minutes >= 0), the
    same defense-in-depth constraint vacation_record/sickness_record already
    have on `hours`. Pre-existing rows must survive the rebuild with their
    data intact, and the new constraint must actually be live afterwards."""
    db_path = tmp_path / "time_clock.db"

    raw = sqlite3.connect(str(db_path))
    raw.execute("PRAGMA foreign_keys=ON;")
    raw.execute("""
        CREATE TABLE time_record (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            date          TEXT    NOT NULL,
            start_time    TEXT    NOT NULL,
            end_time      TEXT    DEFAULT NULL,
            break_minutes INTEGER NOT NULL DEFAULT 0,
            work_type     TEXT    NOT NULL
                CHECK(work_type IN ('in_site', 'road', 'remote')),
            office        TEXT,
            note          TEXT,
            created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
            updated_at    TEXT    NOT NULL DEFAULT (datetime('now')),
            document_path TEXT
        );
    """)
    raw.execute(
        "INSERT INTO time_record (date, start_time, break_minutes, work_type, note) "
        "VALUES ('2026-01-05', '09:00', 30, 'in_site', 'first row'),"
        "('2026-01-06', '10:00', 0, 'remote', 'second row'),"
        "('2026-01-07', '11:00', 45, 'road', 'third row');"
    )
    raw.execute("PRAGMA user_version = 7;")
    raw.commit()
    raw.close()

    db = Database(db_path=str(db_path))
    conn = db.get_connection()

    rows = conn.execute(
        "SELECT date, start_time, break_minutes, work_type, note "
        "FROM time_record ORDER BY date;"
    ).fetchall()
    assert len(rows) == 3
    assert rows[0]["date"] == "2026-01-05"
    assert rows[0]["break_minutes"] == 30
    assert rows[0]["work_type"] == "in_site"
    assert rows[0]["note"] == "first row"
    assert rows[1]["break_minutes"] == 0
    assert rows[1]["note"] == "second row"
    assert rows[2]["break_minutes"] == 45
    assert rows[2]["note"] == "third row"

    # The new constraint must actually be live on the rebuilt table now.
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO time_record (date, start_time, break_minutes, work_type) "
            "VALUES ('2026-02-01', '09:00', -1, 'in_site');"
        )

    # A fresh valid insert must still succeed post-migration.
    conn.execute(
        "INSERT INTO time_record (date, start_time, break_minutes, work_type) "
        "VALUES ('2026-02-02', '09:00', 0, 'in_site');"
    )
    count = conn.execute("SELECT COUNT(*) FROM time_record;").fetchone()[0]
    assert count == 4

    user_version = conn.execute("PRAGMA user_version;").fetchone()[0]
    assert user_version == 8
