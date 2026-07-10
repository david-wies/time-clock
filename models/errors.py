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
