"""JSON-serialized key/value settings persisted to the app_config DB table."""

import copy
import json
import logging
import sqlite3
from typing import Any

from db.database import Database

logger = logging.getLogger(__name__)


class SettingsManager:
    """Reads and writes app settings, JSON-serialized in the app_config DB table."""

    # Default settings dict
    DEFAULTS = {
        "theme": "system",
        "offices": ["Office A", "Office B", "Office C"],
        "break_presets": [15, 30, 45, 60],  # minutes
        "default_work_type": "remote",
        "overtime_rate": 1.0,
        "overtime_period": "month",  # "week" | "month" | "year"
        "view_mode": "month",  # "week" | "month"
        "minimize_to_tray": False,
        # Country/Region for holiday auto-import
        "last_country_holiday": "UnitedStates",
    }

    def __init__(self, db: Database) -> None:
        self.db = db

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieves a configuration value. Falls back to default if not set."""
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM app_config WHERE key = ?;", (key,))
            row = cursor.fetchone()
            if row:
                return json.loads(row["value"])
        except json.JSONDecodeError as exc:
            logger.warning(
                "SettingsManager: corrupted value for key %r, using default: %s",
                key,
                exc,
            )
        except sqlite3.Error as exc:
            logger.warning("SettingsManager: DB read failed for key %r: %s", key, exc)
        finally:
            conn.close()

        # Deep-copy so callers can never mutate the shared DEFAULTS list/dict
        # (or a value returned from a previous call) and corrupt it for the
        # rest of the process's lifetime.
        return copy.deepcopy(self.DEFAULTS.get(key, default))

    def set(self, key: str, value: Any) -> None:
        """Stores a configuration value as JSON-serialized text."""
        serialized = json.dumps(value)
        conn = self.db.get_connection()
        try:
            with conn:
                conn.execute(
                    "INSERT OR REPLACE INTO app_config (key, value) VALUES (?, ?);",
                    (key, serialized),
                )
        finally:
            conn.close()
