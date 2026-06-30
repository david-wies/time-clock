import sqlite3
from datetime import date
from typing import Optional
from domain.types import SicknessRecord, SicknessSummary
from core.events import EventBus, Event
from core.timeutil import iso_to_date, date_to_iso
from db.database import Database


class SicknessModel:
    def __init__(self, db: Database, bus: EventBus) -> None:
        self.db = db
        self.bus = bus

    def _row_to_record(self, row: sqlite3.Row) -> SicknessRecord:
        return SicknessRecord(
            id=row["id"],
            date=iso_to_date(row["date"]),
            hours=row["hours"],
            note=row["note"]
        )

    def get_record_by_id(self, record_id: int) -> Optional[SicknessRecord]:
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM sickness_record WHERE id = ?;", (record_id,))
            row = cursor.fetchone()
            return self._row_to_record(row) if row else None
        finally:
            conn.close()

    def get_records_for_year(self, year: int, month: Optional[int] = None) -> list[SicknessRecord]:
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            if month is not None:
                start_date = f"{year:04d}-{month:02d}-01"
                end_date = f"{year:04d}-{month:02d}-31"
                cursor.execute(
                    "SELECT * FROM sickness_record WHERE date >= ? AND date <= ? ORDER BY date DESC;",
                    (start_date, end_date)
                )
            else:
                start_date = f"{year:04d}-01-01"
                end_date = f"{year:04d}-12-31"
                cursor.execute(
                    "SELECT * FROM sickness_record WHERE date >= ? AND date <= ? ORDER BY date DESC;",
                    (start_date, end_date)
                )
            rows = cursor.fetchall()
            return [self._row_to_record(row) for row in rows]
        finally:
            conn.close()

    def insert_record(self, record: SicknessRecord) -> int:
        conn = self.db.get_connection()
        try:
            with conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO sickness_record (date, hours, note)
                    VALUES (?, ?, ?);
                    """,
                    (
                        date_to_iso(record.date),
                        record.hours,
                        record.note
                    )
                )
                record_id = cursor.lastrowid or 0
            self.bus.publish(Event.SICKNESS_CHANGED)
            return record_id
        finally:
            conn.close()

    def update_record(self, record: SicknessRecord) -> None:
        if record.id is None:
            raise ValueError("Cannot update a record without an ID.")
        conn = self.db.get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    UPDATE sickness_record
                    SET date = ?, hours = ?, note = ?,
                        updated_at = datetime('now')
                    WHERE id = ?;
                    """,
                    (
                        date_to_iso(record.date),
                        record.hours,
                        record.note,
                        record.id
                    )
                )
            self.bus.publish(Event.SICKNESS_CHANGED)
        finally:
            conn.close()

    def delete_record(self, record_id: int) -> None:
        conn = self.db.get_connection()
        try:
            with conn:
                conn.execute(
                    "DELETE FROM sickness_record WHERE id = ?;", (record_id,))
            self.bus.publish(Event.SICKNESS_CHANGED)
        finally:
            conn.close()

    # --- Sickness Settings Queries ---

    def get_settings(self, year: int) -> Optional[float]:
        """Returns days_per_year allowance for the given year."""
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT days_per_year FROM sickness_settings WHERE year = ?;", (year,))
            row = cursor.fetchone()
            return row["days_per_year"] if row else None
        finally:
            conn.close()

    def save_settings(self, year: int, days_per_year: float) -> None:
        conn = self.db.get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO sickness_settings (year, days_per_year)
                    VALUES (?, ?);
                    """,
                    (year, days_per_year)
                )
            self.bus.publish(Event.SETTINGS_CHANGED)
        finally:
            conn.close()

    # --- Sickness Calculations & Summaries ---

    def get_work_day_targets(self) -> dict[int, float]:
        """Returns a dict mapping day_of_week (0-6) to hours."""
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT day_of_week, hours FROM work_day_target;")
            return {row["day_of_week"]: row["hours"] for row in cursor.fetchall()}
        finally:
            conn.close()

    def get_day_equivalent(self, record_date: date, hours: float) -> float:
        """
        Converts sick hours on a given date to day-equivalent.
        Uses daily_target for that date's weekday. Fallback is 8.0h.
        If target is 0.0 (weekend), caps at 1.0 day max (using 8.0h reference).
        """
        weekday = record_date.weekday()  # Monday = 0, Sunday = 6
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT hours FROM work_day_target WHERE day_of_week = ?;", (weekday,))
            row = cursor.fetchone()
            target_hours = row["hours"] if row else None
        finally:
            conn.close()

        # Fallback to 8.0 if no target configured
        if target_hours is None:
            target_hours = 8.0

        if target_hours == 0.0:
            # Weekend / day off: cap at 1.0 day, standard 8h reference (§7.4)
            return min(1.0, hours / 8.0)
        return hours / target_hours

    def calculate_sickness_summary(self, year: int) -> SicknessSummary:
        """
        Calculates sickness totals for a year:
          - allowance: from settings
          - used_hours: sum of raw sickness hours
          - used_days: sum of day-equivalents of sickness records
          - remaining_days: allowance - used_days
        """
        allowance = self.get_settings(year)
        if allowance is None:
            allowance = 10.0  # default fallback from DESIGN.md

        records = self.get_records_for_year(year)

        targets = self.get_work_day_targets()

        used_hours = 0.0
        used_days = 0.0
        for rec in records:
            used_hours += rec.hours
            target_hours = targets.get(rec.date.weekday(), 8.0)
            if target_hours == 0.0:
                day_equiv = min(1.0, rec.hours / 8.0)
            else:
                day_equiv = rec.hours / target_hours
            used_days += day_equiv

        remaining_days = allowance - used_days

        return SicknessSummary(
            allowance=allowance,
            used_hours=used_hours,
            used_days=used_days,
            remaining_days=remaining_days,
        )
