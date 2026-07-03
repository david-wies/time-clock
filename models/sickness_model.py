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
            note=row["note"],
            document_path=row["document_path"],
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

    def get_records_in_date_range(self, start: date, end: date) -> list[SicknessRecord]:
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM sickness_record WHERE date >= ? AND date <= ? ORDER BY date;",
                (date_to_iso(start), date_to_iso(end)),
            )
            return [self._row_to_record(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def insert_record(self, record: SicknessRecord) -> int:
        conn = self.db.get_connection()
        try:
            with conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO sickness_record (date, hours, note, document_path)
                    VALUES (?, ?, ?, ?);
                    """,
                    (
                        date_to_iso(record.date),
                        record.hours,
                        record.note,
                        record.document_path,
                    )
                )
                record_id = cursor.lastrowid or 0
            self.bus.publish(Event.SICKNESS_CHANGED)
            return record_id
        finally:
            conn.close()

    def insert_records_bulk(self, records: list[SicknessRecord]) -> None:
        if not records:
            return
        conn = self.db.get_connection()
        try:
            with conn:
                for record in records:
                    conn.execute(
                        "INSERT INTO sickness_record (date, hours, note, document_path)"
                        " VALUES (?, ?, ?, ?);",
                        (date_to_iso(record.date), record.hours,
                         record.note, record.document_path),
                    )
            self.bus.publish(Event.SICKNESS_CHANGED)
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
                    SET date = ?, hours = ?, note = ?, document_path = ?,
                        updated_at = datetime('now')
                    WHERE id = ?;
                    """,
                    (
                        date_to_iso(record.date),
                        record.hours,
                        record.note,
                        record.document_path,
                        record.id,
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
        """Returns hours_per_year allowance for the given year."""
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT hours_per_year FROM sickness_settings WHERE year = ?;", (year,))
            row = cursor.fetchone()
            return row["hours_per_year"] if row else None
        finally:
            conn.close()

    def save_settings(self, year: int, hours_per_year: float) -> None:
        conn = self.db.get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO sickness_settings (year, hours_per_year)
                    VALUES (?, ?);
                    """,
                    (year, hours_per_year)
                )
            self.bus.publish(Event.SETTINGS_CHANGED)
        finally:
            conn.close()

    # --- Sickness Calculations & Summaries ---

    def calculate_sickness_summary(
        self, year: int, records: Optional[list[SicknessRecord]] = None
    ) -> SicknessSummary:
        """Computes the year's sickness allowance/used/remaining summary.

        If `records` is omitted, the full-year record set is fetched
        internally (existing behavior, unchanged for any caller that
        doesn't already have the records on hand). If the caller already
        fetched the year's records itself (e.g. SicknessTab building both
        the balance summary and the record tree from one fetch per
        refresh), pass them in here to skip the redundant query."""
        allowance = self.get_settings(year)
        if allowance is None:
            allowance = 80.0   # default 10 days × 8 h
        if records is None:
            records = self.get_records_for_year(year)
        used_hours = sum(r.hours for r in records)
        return SicknessSummary(
            allowance_hours=allowance,
            used_hours=used_hours,
            remaining_hours=allowance - used_hours,
        )
