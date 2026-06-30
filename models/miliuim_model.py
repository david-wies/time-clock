import sqlite3
from datetime import date
from typing import Optional
from domain.types import MiliuimRecord, MiliuimSummary
from core.events import EventBus, Event
from core.timeutil import iso_to_date, date_to_iso
from db.database import Database


class MiliuimModel:
    def __init__(self, db: Database, bus: EventBus) -> None:
        self.db = db
        self.bus = bus

    def _row_to_record(self, row: sqlite3.Row) -> MiliuimRecord:
        return MiliuimRecord(
            id=row["id"],
            date=iso_to_date(row["date"]),
            hours=row["hours"],
            note=row["note"],
            document_path=row["document_path"],
        )

    def get_record_by_id(self, record_id: int) -> Optional[MiliuimRecord]:
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM miliuim_record WHERE id = ?;", (record_id,))
            row = cursor.fetchone()
            return self._row_to_record(row) if row else None
        finally:
            conn.close()

    def get_records_for_year(self, year: int, month: Optional[int] = None) -> list[MiliuimRecord]:
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            if month is not None:
                start_date = f"{year:04d}-{month:02d}-01"
                end_date = f"{year:04d}-{month:02d}-31"
                cursor.execute(
                    "SELECT * FROM miliuim_record WHERE date >= ? AND date <= ? ORDER BY date DESC;",
                    (start_date, end_date),
                )
            else:
                start_date = f"{year:04d}-01-01"
                end_date = f"{year:04d}-12-31"
                cursor.execute(
                    "SELECT * FROM miliuim_record WHERE date >= ? AND date <= ? ORDER BY date DESC;",
                    (start_date, end_date),
                )
            return [self._row_to_record(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_records_in_date_range(self, start: date, end: date) -> list[MiliuimRecord]:
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM miliuim_record WHERE date >= ? AND date <= ? ORDER BY date;",
                (date_to_iso(start), date_to_iso(end)),
            )
            return [self._row_to_record(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def insert_record(self, record: MiliuimRecord) -> int:
        conn = self.db.get_connection()
        try:
            with conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO miliuim_record (date, hours, note, document_path) VALUES (?, ?, ?, ?);",
                    (date_to_iso(record.date), record.hours, record.note, record.document_path),
                )
                record_id = cursor.lastrowid or 0
            self.bus.publish(Event.MILIUIM_CHANGED)
            return record_id
        finally:
            conn.close()

    def update_record(self, record: MiliuimRecord) -> None:
        if record.id is None:
            raise ValueError("Cannot update a record without an ID.")
        conn = self.db.get_connection()
        try:
            with conn:
                conn.execute(
                    "UPDATE miliuim_record SET date = ?, hours = ?, note = ?, document_path = ?, updated_at = datetime('now') WHERE id = ?;",
                    (date_to_iso(record.date), record.hours, record.note, record.document_path, record.id),
                )
            self.bus.publish(Event.MILIUIM_CHANGED)
        finally:
            conn.close()

    def delete_record(self, record_id: int) -> None:
        conn = self.db.get_connection()
        try:
            with conn:
                conn.execute("DELETE FROM miliuim_record WHERE id = ?;", (record_id,))
            self.bus.publish(Event.MILIUIM_CHANGED)
        finally:
            conn.close()

    def get_settings(self, year: int) -> Optional[float]:
        """Returns hours_per_year for the given year, or None if not configured."""
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT hours_per_year FROM miliuim_settings WHERE year = ?;", (year,))
            row = cursor.fetchone()
            return row["hours_per_year"] if row else None
        finally:
            conn.close()

    def save_settings(self, year: int, hours_per_year: float) -> None:
        conn = self.db.get_connection()
        try:
            with conn:
                conn.execute(
                    "INSERT OR REPLACE INTO miliuim_settings (year, hours_per_year) VALUES (?, ?);",
                    (year, hours_per_year),
                )
            self.bus.publish(Event.SETTINGS_CHANGED)
        finally:
            conn.close()

    def calculate_summary(self, year: int) -> MiliuimSummary:
        allowance = self.get_settings(year) or 0.0
        records = self.get_records_for_year(year)
        used_hours = sum(r.hours for r in records)
        return MiliuimSummary(
            allowance_hours=allowance,
            used_hours=used_hours,
            remaining_hours=allowance - used_hours,
        )
