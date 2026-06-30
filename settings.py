import json
import sqlite3
import sys
from typing import Any
from db.database import Database


class SettingsManager:
    # Default settings dict
    DEFAULTS = {
        "theme": "system",
        "offices": ["Office A", "Office B", "Office C"],
        "break_presets": [15, 30, 45, 60],  # minutes
        "default_work_type": "remote",
        "overtime_rate": 1.0,
        "overtime_period": "month",  # "week" | "month" | "year"
        "view_mode": "month",        # "week" | "month"
        "minimize_to_tray": False,
        # Country/Region for holiday auto-import
        "last_country_holiday": "UnitedStates"
    }

    def __init__(self, db: Database) -> None:
        self.db = db

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieves a configuration value. Falls back to default if not set."""
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT value FROM app_config WHERE key = ?;", (key,))
            row = cursor.fetchone()
            if row:
                return json.loads(row["value"])
        except json.JSONDecodeError as exc:
            print(f"WARNING: SettingsManager: corrupted value for key {key!r}, using default: {exc}", file=sys.stderr)
        except sqlite3.Error as exc:
            print(f"ERROR: SettingsManager: DB read failed for key {key!r}: {exc}", file=sys.stderr)
        finally:
            conn.close()

        return self.DEFAULTS.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Stores a configuration value as JSON-serialized text."""
        serialized = json.dumps(value)
        conn = self.db.get_connection()
        try:
            with conn:
                conn.execute(
                    "INSERT OR REPLACE INTO app_config (key, value) VALUES (?, ?);",
                    (key, serialized)
                )
        finally:
            conn.close()
