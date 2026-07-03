import calendar
import sqlite3
from datetime import date

from core.events import Event, EventBus
from core.timeutil import date_to_iso, iso_to_date
from db.database import Database
from domain.types import MiliuimRecord, MiliuimSummary


class MiliuimModel:
    def __init__(self, db: Database, bus: EventBus) -> None:
        self.db = db
        self.bus = bus

    def _row_to_record(self, row: sqlite3.Row) -> MiliuimRecord:
        return MiliuimRecord(
            id=row["id"],
            start_date=iso_to_date(row["start_date"]),
            end_date=iso_to_date(row["end_date"]),
            note=row["note"],
            document_path=row["document_path"],
        )

    def get_record_by_id(self, record_id: int) -> MiliuimRecord | None:
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM miliuim_period WHERE id = ?;", (record_id,))
            row = cursor.fetchone()
            return self._row_to_record(row) if row else None

    def get_records_for_year(
        self, year: int, month: int | None = None
    ) -> list[MiliuimRecord]:
        with self.db.connection() as conn:
            cursor = conn.cursor()
            if month is not None:
                last_day = calendar.monthrange(year, month)[1]
                period_start = f"{year:04d}-{month:02d}-01"
                period_end = f"{year:04d}-{month:02d}-{last_day:02d}"
            else:
                period_start = f"{year:04d}-01-01"
                period_end = f"{year:04d}-12-31"
            cursor.execute(
                "SELECT * FROM miliuim_period WHERE start_date <= ? AND end_date >= ?"
                " ORDER BY start_date DESC;",
                (period_end, period_start),
            )
            return [self._row_to_record(row) for row in cursor.fetchall()]

    def get_records_in_date_range(self, start: date, end: date) -> list[MiliuimRecord]:
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM miliuim_period WHERE start_date <= ? AND end_date >= ?"
                " ORDER BY start_date;",
                (date_to_iso(end), date_to_iso(start)),
            )
            return [self._row_to_record(row) for row in cursor.fetchall()]

    def insert_record(self, record: MiliuimRecord) -> int:
        with self.db.connection() as conn:
            with conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO miliuim_period "
                    "(start_date, end_date, note, document_path)"
                    " VALUES (?, ?, ?, ?);",
                    (
                        date_to_iso(record.start_date),
                        date_to_iso(record.end_date),
                        record.note,
                        record.document_path,
                    ),
                )
                record_id = cursor.lastrowid or 0
            self.bus.publish(Event.MILIUIM_CHANGED)
            return record_id

    def update_record(self, record: MiliuimRecord) -> None:
        if record.id is None:
            raise ValueError("Cannot update a record without an ID.")
        with self.db.connection() as conn:
            with conn:
                conn.execute(
                    "UPDATE miliuim_period SET start_date = ?, end_date = ?, note = ?,"
                    " document_path = ?, updated_at = datetime('now') WHERE id = ?;",
                    (
                        date_to_iso(record.start_date),
                        date_to_iso(record.end_date),
                        record.note,
                        record.document_path,
                        record.id,
                    ),
                )
            self.bus.publish(Event.MILIUIM_CHANGED)

    def delete_record(self, record_id: int) -> None:
        with self.db.connection() as conn:
            with conn:
                conn.execute("DELETE FROM miliuim_period WHERE id = ?;", (record_id,))
            self.bus.publish(Event.MILIUIM_CHANGED)

    @staticmethod
    def clip_days(record: MiliuimRecord, year: int, month: int | None = None) -> int:
        """Returns the number of days of `record` that fall within `year`
        (and `month`, if given), clipping the period to that boundary."""
        period_start = date(year, 1, 1)
        period_end = date(year, 12, 31)
        if month is not None:
            last_day = calendar.monthrange(year, month)[1]
            period_start = date(year, month, 1)
            period_end = date(year, month, last_day)
        clipped_start = max(record.start_date, period_start)
        clipped_end = min(record.end_date, period_end)
        if clipped_end < clipped_start:
            return 0
        return (clipped_end - clipped_start).days + 1

    def calculate_summary(self, year: int) -> MiliuimSummary:
        records = self.get_records_for_year(year)
        total_days = sum(self.clip_days(r, year) for r in records)
        return MiliuimSummary(period_count=len(records), total_days=total_days)
