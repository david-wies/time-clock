import os
import sqlite3
import platform
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any


def get_default_db_path() -> Path:
    """Returns the default DB path depending on OS."""
    if platform.system() == "Windows":
        app_data = os.environ.get("APPDATA")
        if app_data:
            base_dir = Path(app_data) / "Time Clock"
        else:
            base_dir = Path.home() / "AppData" / "Roaming" / "Time Clock"
    elif platform.system() == "Darwin":
        base_dir = Path.home() / "Library" / "Application Support" / "Time Clock"
    else:  # Linux / other Unix
        xdg_data = os.environ.get("XDG_DATA_HOME")
        if xdg_data:
            base_dir = Path(xdg_data) / "time-clock"
        else:
            base_dir = Path.home() / ".local" / "share" / "time-clock"

    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir / "time_clock.db"


class SharedConnectionWrapper:
    """Wraps a persistent ``sqlite3.Connection`` and makes ``close()`` a no-op.

    Attribute *reads* (``conn.execute``, ``conn.row_factory``, etc.) are
    forwarded to the wrapped connection via ``__getattr__``. Attribute
    *writes* are NOT forwarded — ``self.x = y`` sets a plain attribute on the
    wrapper itself, exactly like any ordinary object, so future instance
    state added here (or in a subclass) can't silently end up on the
    wrapped ``sqlite3.Connection`` instead.

    ``__enter__``/``__exit__`` must stay explicitly defined (not just
    covered by ``__getattr__``): Python looks up special/dunder methods used
    by implicit protocols (``with conn:``, ``len(conn)``, etc.) on the
    *type*, bypassing instance-level ``__getattr__`` entirely. ``close()``
    must also stay explicit since it deliberately overrides — rather than
    forwards to — the real ``close()``.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)

    def close(self) -> None:
        # No-op to preserve in-memory DB lifetime
        pass

    def __enter__(self) -> "SharedConnectionWrapper":
        self._conn.__enter__()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> Any:
        return self._conn.__exit__(exc_type, exc_val, exc_tb)


class Database:
    def __init__(self, db_path: str | None = None) -> None:
        """
        Initializes the database. If db_path is None, the default OS-specific path is used.
        Pass ':memory:' for in-memory DB testing.
        """
        if db_path is None:
            self.db_path = str(get_default_db_path())
        else:
            self.db_path = db_path

        # A single, persistent connection is opened once here and reused for
        # the lifetime of the app — for :memory: DBs this is required (a
        # fresh connection would see an empty DB every time); for file-based
        # DBs it avoids re-opening + re-configuring a brand new
        # sqlite3.Connection (re-running the PRAGMAs below) on every single
        # get_connection()/connection() call. The `with self.db.connection()
        # as conn:` call sites across models/*.py are unaffected by this: the
        # underlying SharedConnectionWrapper.close() is a no-op, so those
        # call sites safely "close" the shared connection on `with`-exit
        # without ever actually closing it, for both DB kinds.
        raw_conn = sqlite3.connect(self.db_path)
        raw_conn.row_factory = sqlite3.Row
        raw_conn.execute("PRAGMA journal_mode=WAL;")
        raw_conn.execute("PRAGMA foreign_keys=ON;")
        raw_conn.execute("PRAGMA synchronous=NORMAL;")
        self._shared_conn = SharedConnectionWrapper(raw_conn)

        self._init_db()
        return

    def get_connection(self) -> SharedConnectionWrapper:
        """Returns the single persistent connection shared for the app's lifetime."""
        return self._shared_conn

    @contextmanager
    def connection(self) -> Iterator[SharedConnectionWrapper]:
        """Yields the single persistent connection shared for the app's lifetime.

        This exists purely for readable call-site syntax (``with self.db.connection()
        as conn:``); it performs no actual acquire/release. The connection is opened
        once in ``__init__`` and lives for the app's lifetime, and
        ``SharedConnectionWrapper.close()`` is a documented no-op, so there is nothing
        to clean up on exit.
        """
        yield self._shared_conn

    def _init_db(self) -> None:
        """Initializes tables and migrations."""
        conn = self.get_connection()
        try:
            with conn:
                self._create_tables(conn)
                self._apply_migrations(conn)
        finally:
            conn.close()
        return

    def _create_tables(self, conn: sqlite3.Connection) -> None:
        """Creates tables if they do not exist."""
        # 1. Daily work targets
        conn.execute("""
            CREATE TABLE IF NOT EXISTS work_day_target (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                day_of_week INTEGER NOT NULL CHECK(day_of_week BETWEEN 0 AND 6),
                hours       REAL    NOT NULL CHECK(hours >= 0),
                UNIQUE(day_of_week)
            );
        """)

        # 2. Date exception overrides
        conn.execute("""
            CREATE TABLE IF NOT EXISTS work_day_exception (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                date        TEXT    NOT NULL,
                hours       REAL    NOT NULL CHECK(hours >= 0),
                label       TEXT,
                UNIQUE(date)
            );
        """)

        # 3. Time clock records
        conn.execute("""
            CREATE TABLE IF NOT EXISTS time_record (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                date          TEXT    NOT NULL,
                start_time    TEXT    NOT NULL,
                end_time      TEXT    DEFAULT NULL,
                break_minutes INTEGER NOT NULL DEFAULT 0,
                work_type     TEXT    NOT NULL CHECK(work_type IN ('in_site', 'road', 'remote')),
                office        TEXT,
                note          TEXT,
                created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
                updated_at    TEXT    NOT NULL DEFAULT (datetime('now'))
            );
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_time_record_date ON time_record(date);")
        # Partial index supporting get_open_records() and the other
        # `WHERE end_time IS NULL` queries (including the 60s auto-refresh
        # timer) — CREATE INDEX IF NOT EXISTS runs unconditionally on every
        # startup (unlike CREATE TABLE, this isn't gated by user_version),
        # so existing installed DBs pick this up automatically without a
        # migration bump, exactly like idx_time_record_date above.
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_time_record_open "
            "ON time_record(end_time) WHERE end_time IS NULL;")

        # 4. Vacation settings
        conn.execute("""
            CREATE TABLE IF NOT EXISTS vacation_settings (
                year             INTEGER PRIMARY KEY,
                hours_per_year   REAL NOT NULL CHECK(hours_per_year >= 0),
                max_carry_over   REAL NOT NULL CHECK(max_carry_over >= 0)
            );
        """)

        # 5. Vacation records
        conn.execute("""
            CREATE TABLE IF NOT EXISTS vacation_record (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                date        TEXT    NOT NULL,
                hours       REAL    NOT NULL CHECK(hours >= 0),
                vtype       TEXT    NOT NULL CHECK(vtype IN ('annual_leave', 'public_holiday', 'unpaid_leave', 'special_leave', 'carry_over')),
                note        TEXT,
                created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
                updated_at  TEXT    NOT NULL DEFAULT (datetime('now'))
            );
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_vacation_record_date ON vacation_record(date);")

        # 6. Sickness settings
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sickness_settings (
                year             INTEGER PRIMARY KEY,
                days_per_year    REAL NOT NULL CHECK(days_per_year >= 0)
            );
        """)

        # 7. Sickness records
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sickness_record (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                date        TEXT    NOT NULL,
                hours       REAL    NOT NULL CHECK(hours > 0),
                note        TEXT,
                created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
                updated_at  TEXT    NOT NULL DEFAULT (datetime('now'))
            );
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sickness_record_date ON sickness_record(date);")

        # 8. Carry-over log
        conn.execute("""
            CREATE TABLE IF NOT EXISTS carry_over_log (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                from_year       INTEGER NOT NULL,
                to_year         INTEGER NOT NULL,
                hours           REAL    NOT NULL CHECK(hours > 0),
                transferred_at  TEXT    NOT NULL DEFAULT (datetime('now'))
            );
        """)

        # 9. App Configuration
        conn.execute("""
            CREATE TABLE IF NOT EXISTS app_config (
                key             TEXT PRIMARY KEY,
                value           TEXT NOT NULL
            );
        """)

        # Triggers to update updated_at automatically
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_time_record_updated_at AFTER UPDATE ON time_record
            BEGIN
                UPDATE time_record SET updated_at = datetime('now') WHERE id = NEW.id;
            END;
        """)

        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_vacation_record_updated_at AFTER UPDATE ON vacation_record
            BEGIN
                UPDATE vacation_record SET updated_at = datetime('now') WHERE id = NEW.id;
            END;
        """)

        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_sickness_record_updated_at AFTER UPDATE ON sickness_record
            BEGIN
                UPDATE sickness_record SET updated_at = datetime('now') WHERE id = NEW.id;
            END;
        """)
        return

    def _apply_migrations(self, conn: sqlite3.Connection) -> None:
        """Applies schema migrations using user_version."""
        cursor = conn.cursor()
        cursor.execute("PRAGMA user_version;")
        row = cursor.fetchone()
        version = row[0] if row else 0

        # Migration logic (currently at version 1 after setup)
        if version == 0:
            cursor.execute("PRAGMA user_version = 1;")

        if version < 2:
            # Relax vacation_record.hours constraint from > 0 to >= 0 (allow 0-hour holiday imports)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS vacation_record_v2 (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    date        TEXT    NOT NULL,
                    hours       REAL    NOT NULL CHECK(hours >= 0),
                    vtype       TEXT    NOT NULL CHECK(vtype IN ('annual_leave', 'public_holiday', 'unpaid_leave', 'special_leave', 'carry_over')),
                    note        TEXT,
                    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
                    updated_at  TEXT    NOT NULL DEFAULT (datetime('now'))
                );
            """)
            conn.execute(
                "INSERT OR IGNORE INTO vacation_record_v2 SELECT * FROM vacation_record;")
            conn.execute("DROP TABLE vacation_record;")
            conn.execute(
                "ALTER TABLE vacation_record_v2 RENAME TO vacation_record;")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_vacation_record_date ON vacation_record(date);")
            cursor.execute("PRAGMA user_version = 2;")

        if version < 3:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sickness_settings_v3 (
                    year           INTEGER PRIMARY KEY,
                    hours_per_year REAL    NOT NULL CHECK(hours_per_year >= 0)
                )
            """)
            conn.execute(
                "INSERT OR IGNORE INTO sickness_settings_v3 (year, hours_per_year) "
                "SELECT year, days_per_year * 8.0 FROM sickness_settings"
            )
            conn.execute("DROP TABLE IF EXISTS sickness_settings")
            conn.execute(
                "ALTER TABLE sickness_settings_v3 RENAME TO sickness_settings")
            cursor.execute("PRAGMA user_version = 3")

        if version < 4:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS miliuim_settings (
                    year           INTEGER PRIMARY KEY,
                    hours_per_year REAL    NOT NULL CHECK(hours_per_year >= 0)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS miliuim_record (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    date        TEXT    NOT NULL,
                    hours       REAL    NOT NULL CHECK(hours > 0),
                    note        TEXT,
                    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
                    updated_at  TEXT    NOT NULL DEFAULT (datetime('now'))
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_miliuim_record_date ON miliuim_record(date);")
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS trg_miliuim_record_updated_at AFTER UPDATE ON miliuim_record
                BEGIN
                    UPDATE miliuim_record SET updated_at = datetime('now') WHERE id = NEW.id;
                END;
            """)
            cursor.execute("PRAGMA user_version = 4")

        if version < 5:
            conn.execute(
                "ALTER TABLE sickness_record ADD COLUMN document_path TEXT;")
            conn.execute(
                "ALTER TABLE miliuim_record ADD COLUMN document_path TEXT;")
            cursor.execute("PRAGMA user_version = 5")

        if version < 6:
            # Replace per-day miliuim_record + miliuim_settings with miliuim_period (date-range model)
            conn.execute("DROP TABLE IF EXISTS miliuim_settings")
            conn.execute("DROP TABLE IF EXISTS miliuim_record")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS miliuim_period (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    start_date    TEXT    NOT NULL,
                    end_date      TEXT    NOT NULL CHECK(end_date >= start_date),
                    note          TEXT,
                    document_path TEXT,
                    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
                    updated_at    TEXT    NOT NULL DEFAULT (datetime('now'))
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_miliuim_period_start ON miliuim_period(start_date);"
            )
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS trg_miliuim_period_updated_at AFTER UPDATE ON miliuim_period
                BEGIN
                    UPDATE miliuim_period SET updated_at = datetime('now') WHERE id = NEW.id;
                END;
            """)
            cursor.execute("PRAGMA user_version = 6")

        if version < 7:
            conn.execute(
                "ALTER TABLE time_record ADD COLUMN document_path TEXT;")
            cursor.execute("PRAGMA user_version = 7")
        return
