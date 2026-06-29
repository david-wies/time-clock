import sqlite3
from datetime import date, time
from typing import Optional
from domain.types import TimeRecord, WorkDayException
from domain.enums import WorkType
from core.events import EventBus, Event
from core.timeutil import iso_to_date, str_to_time, date_to_iso, time_to_str
from db.database import Database


class TimeClockModel:
    def __init__(self, db: Database, bus: EventBus) -> None:
        self.db = db
        self.bus = bus

    def _row_to_record(self, row: sqlite3.Row) -> TimeRecord:
        return TimeRecord(
            id=row["id"],
            date=iso_to_date(row["date"]),
            start_time=str_to_time(row["start_time"]),
            end_time=str_to_time(row["end_time"]) if row["end_time"] else None,
            break_minutes=row["break_minutes"],
            work_type=WorkType(row["work_type"]),
            office=row["office"],
            note=row["note"]
        )

    def get_record_by_id(self, record_id: int) -> Optional[TimeRecord]:
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM time_record WHERE id = ?;", (record_id,))
            row = cursor.fetchone()
            return self._row_to_record(row) if row else None
        finally:
            conn.close()

    def get_records_by_date(self, target_date: date) -> list[TimeRecord]:
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM time_record WHERE date = ? ORDER BY start_time ASC;",
                (date_to_iso(target_date),)
            )
            rows = cursor.fetchall()
            return [self._row_to_record(row) for row in rows]
        finally:
            conn.close()

    def get_records_for_period(self, year: int, month: Optional[int] = None) -> list[TimeRecord]:
        """
        Retrieves all time records for the given year and optionally month.
        Ordered by date DESC, start_time ASC.
        """
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            if month is not None:
                start_date = f"{year:04d}-{month:02d}-01"
                end_date = f"{year:04d}-{month:02d}-31"
                cursor.execute(
                    "SELECT * FROM time_record WHERE date >= ? AND date <= ? ORDER BY date DESC, start_time ASC;",
                    (start_date, end_date)
                )
            else:
                start_date = f"{year:04d}-01-01"
                end_date = f"{year:04d}-12-31"
                cursor.execute(
                    "SELECT * FROM time_record WHERE date >= ? AND date <= ? ORDER BY date DESC, start_time ASC;",
                    (start_date, end_date)
                )
            rows = cursor.fetchall()
            return [self._row_to_record(row) for row in rows]
        finally:
            conn.close()

    def get_open_records(self) -> list[TimeRecord]:
        """Finds all records that are currently open (end_time is NULL), across all dates."""
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM time_record WHERE end_time IS NULL ORDER BY date DESC, start_time ASC;")
            rows = cursor.fetchall()
            return [self._row_to_record(row) for row in rows]
        finally:
            conn.close()

    def get_open_records_for_date(self, d: date) -> list[TimeRecord]:
        """Finds open records (end_time IS NULL) for a specific date (§10.4, §10.5)."""
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM time_record WHERE date = ? AND end_time IS NULL ORDER BY start_time ASC;",
                (d.isoformat(),)
            )
            rows = cursor.fetchall()
            return [self._row_to_record(row) for row in rows]
        finally:
            conn.close()

    def get_open_records_for_today(self) -> list[TimeRecord]:
        """Finds open records (end_time IS NULL) for today only. Convenience wrapper."""
        return self.get_open_records_for_date(date.today())

    def insert_record(self, record: TimeRecord) -> int:
        conn = self.db.get_connection()
        try:
            with conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO time_record (date, start_time, end_time, break_minutes, work_type, office, note)
                    VALUES (?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        date_to_iso(record.date),
                        time_to_str(record.start_time),
                        time_to_str(
                            record.end_time) if record.end_time else None,
                        record.break_minutes,
                        record.work_type.value,
                        record.office,
                        record.note
                    )
                )
                record_id = cursor.lastrowid or 0
            self.bus.publish(Event.TIME_RECORDS_CHANGED)
            return record_id
        finally:
            conn.close()

    def update_record(self, record: TimeRecord) -> None:
        if record.id is None:
            raise ValueError("Cannot update a record without an ID.")
        conn = self.db.get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    UPDATE time_record
                    SET date = ?, start_time = ?, end_time = ?, break_minutes = ?, work_type = ?, office = ?, note = ?,
                        updated_at = datetime('now')
                    WHERE id = ?;
                    """,
                    (
                        date_to_iso(record.date),
                        time_to_str(record.start_time),
                        time_to_str(
                            record.end_time) if record.end_time else None,
                        record.break_minutes,
                        record.work_type.value,
                        record.office,
                        record.note,
                        record.id
                    )
                )
            self.bus.publish(Event.TIME_RECORDS_CHANGED)
        finally:
            conn.close()

    def delete_record(self, record_id: int) -> None:
        conn = self.db.get_connection()
        try:
            with conn:
                conn.execute(
                    "DELETE FROM time_record WHERE id = ?;", (record_id,))
            self.bus.publish(Event.TIME_RECORDS_CHANGED)
        finally:
            conn.close()

    # --- Target Hours & Exceptions Queries ---

    def get_work_day_targets(self) -> dict[int, float]:
        """Returns a dict mapping day_of_week (0-6) to hours."""
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT day_of_week, hours FROM work_day_target;")
            rows = cursor.fetchall()
            return {row["day_of_week"]: row["hours"] for row in rows}
        finally:
            conn.close()

    def save_work_day_targets(self, targets: dict[int, float]) -> None:
        conn = self.db.get_connection()
        try:
            with conn:
                for day_of_week, hours in targets.items():
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO work_day_target (day_of_week, hours)
                        VALUES (?, ?);
                        """,
                        (day_of_week, hours)
                    )
            self.bus.publish(Event.SETTINGS_CHANGED)
        finally:
            conn.close()

    def get_date_exceptions(self, year: Optional[int] = None) -> list[WorkDayException]:
        """Returns work day exceptions. If year is specified, filters by that year."""
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            if year is not None:
                start_date = f"{year:04d}-01-01"
                end_date = f"{year:04d}-12-31"
                cursor.execute(
                    "SELECT id, date, hours, label FROM work_day_exception WHERE date >= ? AND date <= ? ORDER BY date ASC;",
                    (start_date, end_date)
                )
            else:
                cursor.execute(
                    "SELECT id, date, hours, label FROM work_day_exception ORDER BY date ASC;")
            rows = cursor.fetchall()
            return [
                WorkDayException(
                    id=row["id"],
                    date=row["date"],
                    hours=row["hours"],
                    label=row["label"],
                )
                for row in rows
            ]
        finally:
            conn.close()

    def save_date_exception(self, date_str: str, hours: float, label: Optional[str] = None) -> None:
        conn = self.db.get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO work_day_exception (date, hours, label)
                    VALUES (?, ?, ?);
                    """,
                    (date_str, hours, label)
                )
            self.bus.publish(Event.SETTINGS_CHANGED)
        finally:
            conn.close()

    def delete_date_exception(self, exception_id: int) -> None:
        conn = self.db.get_connection()
        try:
            with conn:
                conn.execute(
                    "DELETE FROM work_day_exception WHERE id = ?;", (exception_id,))
            self.bus.publish(Event.SETTINGS_CHANGED)
        finally:
            conn.close()

    def delete_date_exception_by_date(self, date_str: str) -> None:
        conn = self.db.get_connection()
        try:
            with conn:
                conn.execute(
                    "DELETE FROM work_day_exception WHERE date = ?;", (date_str,))
            self.bus.publish(Event.SETTINGS_CHANGED)
        finally:
            conn.close()
