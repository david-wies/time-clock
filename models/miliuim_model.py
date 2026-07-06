"""Model for Miliuim (reserve-duty) records: DB row/dataclass mapping and CRUD."""

import calendar
import logging
import sqlite3
from datetime import date

from core.events import Event, EventBus
from core.timeutil import date_to_iso, iso_to_date, period_bounds
from db.database import Database
from domain.types import MiliuimRecord, MiliuimSummary

logger = logging.getLogger(__name__)


class MiliuimModel:
    """Manages Miliuim (reserve-duty) period records and their summaries."""

    def __init__(self, db: Database, bus: EventBus) -> None:
        self.db = db
        self.bus = bus
        # Set by _rows_to_records() at the end of every list-fetch call
        # (get_records_for_year(), etc.) to the number of malformed rows
        # that call silently dropped. The app is single-threaded/
        # synchronous, so a caller can safely read this right after the
        # fetch it corresponds to -- see
        # views/record_tab_common.py:RecordTabMixin._append_skip_notice().
        self.last_skipped_count = 0

    def _row_to_record(self, row: sqlite3.Row) -> MiliuimRecord | None:
        """Builds a MiliuimRecord from a DB row, or None (with a logged
        warning) if the row violates a MiliuimRecord invariant -- e.g. an
        overlong note, or an end_date before start_date, added directly to
        the DB. Without this guard, a single malformed row would raise out
        of every read method and take down the whole query."""
        try:
            return MiliuimRecord(
                id=row["id"],
                start_date=iso_to_date(row["start_date"]),
                end_date=iso_to_date(row["end_date"]),
                note=row["note"],
                document_path=row["document_path"],
            )
        except ValueError:
            logger.warning(
                "Skipping malformed miliuim_period row: id=%r start_date=%r",
                row["id"],
                row["start_date"],
            )
            return None

    def _rows_to_records(self, rows: list[sqlite3.Row]) -> list[MiliuimRecord]:
        records = []
        for row in rows:
            rec = self._row_to_record(row)
            if rec is not None:
                records.append(rec)
        self.last_skipped_count = len(rows) - len(records)
        return records

    def get_record_by_id(self, record_id: int) -> MiliuimRecord | None:
        """Returns the Miliuim record with the given id, or None if not found."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM miliuim_period WHERE id = ?;", (record_id,))
            row = cursor.fetchone()
            return self._row_to_record(row) if row else None

    def get_records_for_year(
        self, year: int, month: int | None = None
    ) -> list[MiliuimRecord]:
        """Returns all Miliuim periods overlapping the given year, optionally
        filtered to a month, ordered by start_date DESC."""
        period_start, period_end = period_bounds(year, month)
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM miliuim_period WHERE start_date <= ? AND end_date >= ?"
                " ORDER BY start_date DESC;",
                (period_end, period_start),
            )
            return self._rows_to_records(cursor.fetchall())

    def get_records_in_date_range(self, start: date, end: date) -> list[MiliuimRecord]:
        """Returns all Miliuim periods overlapping [start, end], ordered by
        start_date ASC."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM miliuim_period WHERE start_date <= ? AND end_date >= ?"
                " ORDER BY start_date;",
                (date_to_iso(end), date_to_iso(start)),
            )
            return self._rows_to_records(cursor.fetchall())

    def get_date_ranges_in_range(
        self, start: date, end: date
    ) -> list[tuple[int, date, date]]:
        """Returns (id, start_date, end_date) for every miliuim_period row
        overlapping [start, end], via a raw SQL read that never constructs a
        MiliuimRecord.

        Unlike get_records_in_date_range(), this cannot silently drop a row
        for failing a MiliuimRecord invariant (e.g. an overlong note from
        before the 500-char limit existed, or a restored backup):
        MiliuimController.save_record()'s overlap check needs every
        overlapping period to be visible, and
        get_records_in_date_range() -> _row_to_record() would otherwise
        catch and skip such a row.

        A row whose start_date/end_date string is not itself a parseable
        ISO date (corrupt data, a bad migration, a hand-edited DB) is a
        different failure mode -- there is no date to compare for overlap --
        so that row, and only that row, is logged and skipped.
        """
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, start_date, end_date FROM miliuim_period"
                " WHERE start_date <= ? AND end_date >= ? ORDER BY start_date;",
                (date_to_iso(end), date_to_iso(start)),
            )
            ranges: list[tuple[int, date, date]] = []
            for row in cursor.fetchall():
                try:
                    ranges.append(
                        (
                            row["id"],
                            iso_to_date(row["start_date"]),
                            iso_to_date(row["end_date"]),
                        )
                    )
                except ValueError:
                    logger.warning(
                        "Skipping miliuim_period row with unparseable date:"
                        " id=%r start_date=%r end_date=%r",
                        row["id"],
                        row["start_date"],
                        row["end_date"],
                    )
            return ranges

    def insert_record(self, record: MiliuimRecord) -> int:
        """Inserts a new Miliuim period record and returns its id."""
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
        """Updates an existing Miliuim period record identified by its id."""
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
        """Deletes the Miliuim period record with the given id."""
        with self.db.connection() as conn:
            with conn:
                conn.execute(
                    "DELETE FROM miliuim_period WHERE id = ?;", (record_id,))
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

    def calculate_summary(
        self, year: int, records: list[MiliuimRecord] | None = None
    ) -> MiliuimSummary:
        """Computes the year's Miliuim period-count/total-days summary.

        If `records` is omitted, the full-year record set is fetched
        internally (existing behavior, unchanged for any caller that
        doesn't already have the records on hand). If the caller already
        fetched the year's records itself (e.g. MiliuimTab building both
        the balance summary and the record tree from one fetch per
        refresh), pass them in here to skip the redundant query. Mirrors
        VacationModel.calculate_vacation_summary() and
        SicknessModel.calculate_sickness_summary().
        """
        if records is None:
            records = self.get_records_for_year(year)
        total_days = sum(self.clip_days(r, year) for r in records)
        return MiliuimSummary(period_count=len(records), total_days=total_days)
