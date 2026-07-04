import logging
import sqlite3
from datetime import date

from core.events import Event, EventBus
from core.timeutil import date_to_iso, iso_to_date, period_bounds
from db.database import Database
from domain.types import SicknessRecord, SicknessSummary

logger = logging.getLogger(__name__)


class SicknessModel:
    def __init__(self, db: Database, bus: EventBus) -> None:
        self.db = db
        self.bus = bus

    def _row_to_record(self, row: sqlite3.Row) -> SicknessRecord | None:
        """Builds a SicknessRecord from a DB row, or None (with a logged
        warning) if the row violates a SicknessRecord invariant -- e.g. an
        overlong note added directly to the DB. Without this guard, a single
        malformed row would raise out of every read method and take down
        the whole query."""
        try:
            return SicknessRecord(
                id=row["id"],
                date=iso_to_date(row["date"]),
                hours=row["hours"],
                note=row["note"],
                document_path=row["document_path"],
            )
        except ValueError:
            logger.warning(
                "Skipping malformed sickness_record row: id=%r date=%r",
                row["id"],
                row["date"],
            )
            return None

    def _rows_to_records(self, rows: list[sqlite3.Row]) -> list[SicknessRecord]:
        records = []
        for row in rows:
            rec = self._row_to_record(row)
            if rec is not None:
                records.append(rec)
        return records

    def get_record_by_id(self, record_id: int) -> SicknessRecord | None:
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM sickness_record WHERE id = ?;", (record_id,))
            row = cursor.fetchone()
            return self._row_to_record(row) if row else None

    def get_records_for_year(
        self, year: int, month: int | None = None
    ) -> list[SicknessRecord]:
        start_date, end_date = period_bounds(year, month)
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM sickness_record WHERE date >= ? AND date <= ? "
                "ORDER BY date DESC;",
                (start_date, end_date),
            )
            rows = cursor.fetchall()
            return self._rows_to_records(rows)

    def get_records_in_date_range(self, start: date, end: date) -> list[SicknessRecord]:
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM sickness_record WHERE date >= ? AND date <= ? "
                "ORDER BY date;",
                (date_to_iso(start), date_to_iso(end)),
            )
            return self._rows_to_records(cursor.fetchall())

    def insert_record(self, record: SicknessRecord) -> int:
        with self.db.connection() as conn:
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
                    ),
                )
                record_id = cursor.lastrowid or 0
            self.bus.publish(Event.SICKNESS_CHANGED)
            return record_id

    def insert_records_bulk(self, records: list[SicknessRecord]) -> None:
        if not records:
            return
        with self.db.connection() as conn:
            with conn:
                for record in records:
                    conn.execute(
                        "INSERT INTO sickness_record (date, hours, note, document_path)"
                        " VALUES (?, ?, ?, ?);",
                        (
                            date_to_iso(record.date),
                            record.hours,
                            record.note,
                            record.document_path,
                        ),
                    )
            self.bus.publish(Event.SICKNESS_CHANGED)

    def update_record(self, record: SicknessRecord) -> None:
        if record.id is None:
            raise ValueError("Cannot update a record without an ID.")
        with self.db.connection() as conn:
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
                    ),
                )
            self.bus.publish(Event.SICKNESS_CHANGED)

    def delete_record(self, record_id: int) -> None:
        with self.db.connection() as conn:
            with conn:
                conn.execute("DELETE FROM sickness_record WHERE id = ?;", (record_id,))
            self.bus.publish(Event.SICKNESS_CHANGED)

    # --- Sickness Settings Queries ---

    def get_settings(self, year: int) -> float | None:
        """Returns hours_per_year allowance for the given year."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT hours_per_year FROM sickness_settings WHERE year = ?;", (year,)
            )
            row = cursor.fetchone()
            return row["hours_per_year"] if row else None

    def save_settings(self, year: int, hours_per_year: float) -> None:
        with self.db.connection() as conn:
            with conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO sickness_settings (year, hours_per_year)
                    VALUES (?, ?);
                    """,
                    (year, hours_per_year),
                )
            self.bus.publish(Event.SETTINGS_CHANGED)

    # --- Sickness Calculations & Summaries ---

    def calculate_sickness_summary(
        self, year: int, records: list[SicknessRecord] | None = None
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
            allowance = 80.0  # default 10 days × 8 h
        if records is None:
            records = self.get_records_for_year(year)
        used_hours = sum(r.hours for r in records)
        return SicknessSummary(
            allowance_hours=allowance,
            used_hours=used_hours,
            remaining_hours=allowance - used_hours,
        )
