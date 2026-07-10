"""Model for time clock records: DB row/dataclass mapping and CRUD."""

import logging
import sqlite3
from datetime import date, time

from core.events import Event, EventBus
from core.timeutil import (
    date_to_iso,
    iso_to_date,
    period_bounds,
    str_to_time,
    time_to_str,
)
from db.database import Database
from domain.enums import WorkType
from domain.types import TimeRecord, WorkDayException
from models._row_mapping import rows_to_records
from models.errors import raise_if_no_rows

logger = logging.getLogger(__name__)


class TimeClockModel:
    """Manages time clock records and work-day target/exception settings."""

    def __init__(self, db: Database, bus: EventBus) -> None:
        self.db = db
        self.bus = bus
        # Set by _rows_to_records() at the end of every list-fetch call
        # (get_records_by_date(), get_records_for_period(), etc.) to the
        # number of malformed rows that call silently dropped. The app is
        # single-threaded/synchronous, so a caller can safely read this
        # right after the fetch it corresponds to -- see
        # views/record_tab_common.py:RecordTabMixin._append_skip_notice().
        self.last_skipped_count = 0

    def _row_to_record(self, row: sqlite3.Row) -> TimeRecord | None:
        """Builds a TimeRecord from a DB row, or None (with a logged
        warning) if the row violates a TimeRecord invariant -- e.g. a
        legacy/manually-edited row whose break_minutes exceeds its shift
        length. Without this guard, a single malformed row would raise out
        of every read method and take down the whole query."""
        try:
            return TimeRecord(
                id=row["id"],
                date=iso_to_date(row["date"]),
                start_time=str_to_time(row["start_time"]),
                end_time=str_to_time(row["end_time"]) if row["end_time"] else None,
                break_minutes=row["break_minutes"],
                work_type=WorkType(row["work_type"]),
                office=row["office"],
                note=row["note"],
                document_path=row["document_path"],
            )
        except (ValueError, TypeError):  # fmt: skip
            logger.warning(
                "Skipping malformed time_record row: id=%r date=%r",
                row["id"],
                row["date"],
            )
            return None

    def _rows_to_records(self, rows: list[sqlite3.Row]) -> list[TimeRecord]:
        records, self.last_skipped_count = rows_to_records(rows, self._row_to_record)
        return records

    def get_record_by_id(self, record_id: int) -> TimeRecord | None:
        """Returns the time record with the given id, or None if not found."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM time_record WHERE id = ?;", (record_id,))
            row = cursor.fetchone()
            return self._row_to_record(row) if row else None

    def get_records_by_date(self, target_date: date) -> list[TimeRecord]:
        """Returns all time records for the given date, ordered by start_time ASC."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM time_record WHERE date = ? ORDER BY start_time ASC;",
                (date_to_iso(target_date),),
            )
            rows = cursor.fetchall()
            return self._rows_to_records(rows)

    def get_time_ranges_by_date(
        self, target_date: date
    ) -> list[tuple[int, time, time | None]]:
        """Returns (id, start_time, end_time) for every time_record row on
        `target_date`, via a raw SQL read that never constructs a
        TimeRecord.

        Unlike get_records_by_date(), this cannot silently drop a row:
        the overlap check in TimeClockController.save_record()/clock_in()/
        clock_out() needs every existing record for the day to be visible,
        including a pre-existing row that would fail TimeRecord's
        invariants (e.g. a legacy break_minutes exceeding shift length, or
        a missing office for a WorkType.IN_SITE row added before that
        requirement existed) and that get_records_by_date() ->
        _row_to_record() would otherwise catch and skip. Mirrors
        MiliuimModel.get_date_ranges_in_range().

        A row whose start_time/end_time string is not itself a parseable
        time (corrupt data, a bad migration, a hand-edited DB) is a
        different failure mode -- there is no time to compare for overlap --
        so that row, and only that row, is logged and skipped.
        """
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, start_time, end_time FROM time_record"
                " WHERE date = ? ORDER BY start_time ASC;",
                (date_to_iso(target_date),),
            )
            ranges: list[tuple[int, time, time | None]] = []
            for row in cursor.fetchall():
                try:
                    start = str_to_time(row["start_time"])
                    end = str_to_time(row["end_time"]) if row["end_time"] else None
                except (ValueError, TypeError):  # fmt: skip
                    logger.warning(
                        "Skipping time_record row with unparseable time:"
                        " id=%r start_time=%r end_time=%r",
                        row["id"],
                        row["start_time"],
                        row["end_time"],
                    )
                    continue
                ranges.append((row["id"], start, end))
            return ranges

    def get_records_for_period(
        self, year: int, month: int | None = None
    ) -> list[TimeRecord]:
        """
        Retrieves all time records for the given year and optionally month.
        Ordered by date DESC, start_time ASC.
        """
        start_date, end_date = period_bounds(year, month)
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM time_record WHERE date >= ? AND date <= ? "
                "ORDER BY date DESC, start_time ASC;",
                (start_date, end_date),
            )
            rows = cursor.fetchall()
            return self._rows_to_records(rows)

    def get_records_for_date_range(self, start: date, end: date) -> list[TimeRecord]:
        """Returns all time records whose date falls in [start, end].

        Ordered by date ASC, start_time ASC.
        """
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM time_record WHERE date >= ? AND date <= ? "
                "ORDER BY date ASC, start_time ASC;",
                (date_to_iso(start), date_to_iso(end)),
            )
            return self._rows_to_records(cursor.fetchall())

    def get_open_records(self) -> list[TimeRecord]:
        """Finds all records that are currently open (end_time is NULL).

        Considers records across all dates.
        """
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM time_record WHERE end_time IS NULL "
                "ORDER BY date DESC, start_time ASC;"
            )
            rows = cursor.fetchall()
            return self._rows_to_records(rows)

    def get_open_records_for_date(self, d: date) -> list[TimeRecord]:
        """Finds open records (end_time IS NULL) for a specific date (§10.4, §10.5)."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM time_record WHERE date = ? AND end_time IS NULL "
                "ORDER BY start_time ASC;",
                (d.isoformat(),),
            )
            rows = cursor.fetchall()
            return self._rows_to_records(rows)

    def get_open_records_for_today(self) -> list[TimeRecord]:
        """Finds open records (end_time IS NULL) for today only. Convenience wrapper."""
        return self.get_open_records_for_date(date.today())

    def insert_record(self, record: TimeRecord) -> int:
        """Inserts a new time record and returns its id."""
        with self.db.connection() as conn:
            with conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO time_record (
                        date, start_time, end_time, break_minutes,
                        work_type, office, note, document_path
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        date_to_iso(record.date),
                        time_to_str(record.start_time),
                        time_to_str(record.end_time) if record.end_time else None,
                        record.break_minutes,
                        record.work_type.value,
                        record.office,
                        record.note,
                        record.document_path,
                    ),
                )
                record_id = cursor.lastrowid or 0
            self.bus.publish(Event.TIME_RECORDS_CHANGED)
            return record_id

    def update_record(self, record: TimeRecord) -> None:
        """Updates an existing time record identified by its id."""
        if record.id is None:
            raise ValueError("Cannot update a record without an ID.")
        with self.db.connection() as conn:
            with conn:
                cursor = conn.execute(
                    """
                    UPDATE time_record
                    SET date = ?, start_time = ?, end_time = ?, break_minutes = ?,
                        work_type = ?, office = ?, note = ?,
                        document_path = ?, updated_at = datetime('now')
                    WHERE id = ?;
                    """,
                    (
                        date_to_iso(record.date),
                        time_to_str(record.start_time),
                        time_to_str(record.end_time) if record.end_time else None,
                        record.break_minutes,
                        record.work_type.value,
                        record.office,
                        record.note,
                        record.document_path,
                        record.id,
                    ),
                )
                raise_if_no_rows(cursor, "time record", record.id, "update")
            self.bus.publish(Event.TIME_RECORDS_CHANGED)

    def delete_record(self, record_id: int) -> None:
        """Deletes the time record with the given id."""
        with self.db.connection() as conn:
            with conn:
                cursor = conn.execute(
                    "DELETE FROM time_record WHERE id = ?;", (record_id,)
                )
                raise_if_no_rows(cursor, "time_record", record_id, "delete")
            self.bus.publish(Event.TIME_RECORDS_CHANGED)

    # --- Target Hours & Exceptions Queries ---

    def get_work_day_targets(self) -> dict[int, float]:
        """Returns a dict mapping day_of_week (0-6) to hours."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT day_of_week, hours FROM work_day_target;")
            rows = cursor.fetchall()
            return {row["day_of_week"]: row["hours"] for row in rows}

    def save_work_day_targets(self, targets: dict[int, float]) -> None:
        """Upserts the hours target for each day_of_week given in `targets`."""
        with self.db.connection() as conn:
            with conn:
                for day_of_week, hours in targets.items():
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO work_day_target (day_of_week, hours)
                        VALUES (?, ?);
                        """,
                        (day_of_week, hours),
                    )
            self.bus.publish(Event.SETTINGS_CHANGED)

    def get_date_exceptions(self, year: int | None = None) -> list[WorkDayException]:
        """Returns work day exceptions. If year is specified, filters by that year."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            if year is not None:
                start_date = f"{year:04d}-01-01"
                end_date = f"{year:04d}-12-31"
                cursor.execute(
                    "SELECT id, date, hours, label FROM work_day_exception "
                    "WHERE date >= ? AND date <= ? ORDER BY date ASC;",
                    (start_date, end_date),
                )
            else:
                cursor.execute(
                    "SELECT id, date, hours, label FROM work_day_exception "
                    "ORDER BY date ASC;"
                )
            rows = cursor.fetchall()
            exceptions = []
            for row in rows:
                try:
                    exc_date = date.fromisoformat(row["date"])
                except (ValueError, TypeError):  # fmt: skip
                    logger.warning(
                        "Skipping malformed work-day exception row "
                        "(falls back to the regular weekly target for that "
                        "date): id=%r date=%r",
                        row["id"],
                        row["date"],
                    )
                    continue
                try:
                    exception = WorkDayException(
                        id=row["id"],
                        date=exc_date,
                        hours=row["hours"],
                        label=row["label"],
                    )
                except (ValueError, TypeError):  # fmt: skip
                    logger.warning(
                        "Skipping malformed work-day exception row "
                        "(falls back to the regular weekly target for that "
                        "date): id=%r date=%r hours=%r",
                        row["id"],
                        row["date"],
                        row["hours"],
                    )
                    continue
                exceptions.append(exception)
            return exceptions

    def save_date_exception(
        self, date_str: str, hours: float, label: str | None = None
    ) -> None:
        """Upserts a work-day exception (target hours override) for a specific date."""
        with self.db.connection() as conn:
            with conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO work_day_exception (date, hours, label)
                    VALUES (?, ?, ?);
                    """,
                    (date_str, hours, label),
                )
            self.bus.publish(Event.SETTINGS_CHANGED)

    def delete_date_exception(self, exception_id: int) -> None:
        """Deletes the work-day exception with the given id."""
        with self.db.connection() as conn:
            with conn:
                conn.execute(
                    "DELETE FROM work_day_exception WHERE id = ?;", (exception_id,)
                )
            self.bus.publish(Event.SETTINGS_CHANGED)

    def delete_date_exception_by_date(self, date_str: str) -> None:
        """Deletes the work-day exception for the given ISO date string."""
        with self.db.connection() as conn:
            with conn:
                conn.execute(
                    "DELETE FROM work_day_exception WHERE date = ?;", (date_str,)
                )
            self.bus.publish(Event.SETTINGS_CHANGED)
