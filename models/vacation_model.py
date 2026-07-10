"""Model for vacation records: DB row/dataclass mapping and CRUD."""

import logging
import sqlite3
from datetime import date, datetime
from typing import Any

from core.events import Event, EventBus
from core.timeutil import date_to_iso, iso_to_date, period_bounds
from db.database import Database
from domain.enums import VacationType
from domain.types import (
    CarryOverAllowance,
    CarryOverLogEntry,
    VacationRecord,
    VacationSummary,
)
from models._row_mapping import rows_to_records

logger = logging.getLogger(__name__)


class VacationModel:
    """Manages vacation records, allowance settings, and carry-over calculations."""

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

    def _row_to_record(self, row: sqlite3.Row) -> VacationRecord | None:
        """Builds a VacationRecord from a DB row, or None (with a logged
        warning) if the row violates a VacationRecord invariant -- e.g. an
        overlong note added directly to the DB. Without this guard, a single
        malformed row would raise out of every read method and take down
        the whole query."""
        try:
            return VacationRecord(
                id=row["id"],
                date=iso_to_date(row["date"]),
                hours=row["hours"],
                vtype=VacationType(row["vtype"]),
                note=row["note"],
            )
        except (ValueError, TypeError):  # fmt: skip
            logger.warning(
                "Skipping malformed vacation_record row: id=%r date=%r",
                row["id"],
                row["date"],
            )
            return None

    def _rows_to_records(self, rows: list[sqlite3.Row]) -> list[VacationRecord]:
        records, self.last_skipped_count = rows_to_records(rows, self._row_to_record)
        return records

    def get_record_by_id(self, record_id: int) -> VacationRecord | None:
        """Returns the vacation record with the given id, or None if not found."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM vacation_record WHERE id = ?;", (record_id,))
            row = cursor.fetchone()
            return self._row_to_record(row) if row else None

    def get_records_for_year(
        self, year: int, month: int | None = None
    ) -> list[VacationRecord]:
        """Returns all vacation records for the given year, optionally filtered
        to a month, ordered by date DESC."""
        start_date, end_date = period_bounds(year, month)
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM vacation_record WHERE date >= ? AND date <= ? "
                "ORDER BY date DESC;",
                (start_date, end_date),
            )
            rows = cursor.fetchall()
            return self._rows_to_records(rows)

    def insert_record(self, record: VacationRecord) -> int:
        """Inserts a new vacation record and returns its id."""
        with self.db.connection() as conn:
            with conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO vacation_record (date, hours, vtype, note)
                    VALUES (?, ?, ?, ?);
                    """,
                    (
                        date_to_iso(record.date),
                        record.hours,
                        record.vtype.value,
                        record.note,
                    ),
                )
                record_id = cursor.lastrowid or 0
            self.bus.publish(Event.VACATION_CHANGED)
            return record_id

    def update_record(self, record: VacationRecord) -> None:
        """Updates an existing vacation record identified by its id."""
        if record.id is None:
            raise ValueError("Cannot update a record without an ID.")
        with self.db.connection() as conn:
            with conn:
                cursor = conn.execute(
                    """
                    UPDATE vacation_record
                    SET date = ?, hours = ?, vtype = ?, note = ?,
                        updated_at = datetime('now')
                    WHERE id = ?;
                    """,
                    (
                        date_to_iso(record.date),
                        record.hours,
                        record.vtype.value,
                        record.note,
                        record.id,
                    ),
                )
                if cursor.rowcount == 0:
                    raise sqlite3.DatabaseError(
                        f"No vacation record with id={record.id} exists to update"
                    )
            self.bus.publish(Event.VACATION_CHANGED)

    def delete_record(self, record_id: int) -> None:
        """Deletes the vacation record with the given id."""
        with self.db.connection() as conn:
            with conn:
                cursor = conn.execute(
                    "DELETE FROM vacation_record WHERE id = ?;", (record_id,)
                )
                if cursor.rowcount == 0:
                    raise sqlite3.DatabaseError(
                        f"No vacation_record with id={record_id} exists to delete"
                    )
            self.bus.publish(Event.VACATION_CHANGED)

    # --- Vacation Settings Queries ---

    def get_settings(self, year: int) -> dict[str, Any] | None:
        """Returns hours_per_year and max_carry_over for the given year, or
        None if not configured."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT hours_per_year, max_carry_over FROM vacation_settings "
                "WHERE year = ?;",
                (year,),
            )
            row = cursor.fetchone()
            if row:
                return {
                    "hours_per_year": row["hours_per_year"],
                    "max_carry_over": row["max_carry_over"],
                }
            return None

    def save_settings(
        self, year: int, hours_per_year: float, max_carry_over: float
    ) -> None:
        """Upserts the vacation hours_per_year and max_carry_over for the given year."""
        with self.db.connection() as conn:
            with conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO vacation_settings
                        (year, hours_per_year, max_carry_over)
                    VALUES (?, ?, ?);
                    """,
                    (year, hours_per_year, max_carry_over),
                )
            self.bus.publish(Event.SETTINGS_CHANGED)

    # --- Carry-Over Calculations & Logging ---

    def get_carry_over_history(self, to_year: int) -> list[CarryOverLogEntry]:
        """Returns list of carry-over log details for the destination year."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, from_year, to_year, hours, transferred_at "
                "FROM carry_over_log WHERE to_year = ?;",
                (to_year,),
            )
            rows = cursor.fetchall()
            entries = []
            skipped_count = 0
            for row in rows:
                try:
                    transferred_at = datetime.fromisoformat(row["transferred_at"])
                except (ValueError, TypeError):  # fmt: skip
                    logger.warning(
                        "Skipping malformed carry_over_log row: "
                        "id=%r transferred_at=%r",
                        row["id"],
                        row["transferred_at"],
                    )
                    skipped_count += 1
                    continue
                try:
                    entries.append(
                        CarryOverLogEntry(
                            id=row["id"],
                            from_year=row["from_year"],
                            to_year=row["to_year"],
                            hours=row["hours"],
                            transferred_at=transferred_at,
                        )
                    )
                except (ValueError, TypeError):  # fmt: skip
                    logger.warning(
                        "Skipping malformed carry_over_log row: id=%r "
                        "from_year=%r to_year=%r hours=%r",
                        row["id"],
                        row["from_year"],
                        row["to_year"],
                        row["hours"],
                    )
                    skipped_count += 1
            self.last_skipped_count = skipped_count
            return entries

    def get_already_transferred(self, from_year: int, to_year: int) -> float:
        """Returns sum of hours already transferred from from_year to to_year."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT SUM(hours) as total FROM carry_over_log "
                "WHERE from_year = ? AND to_year = ?;",
                (from_year, to_year),
            )
            row = cursor.fetchone()
            return row["total"] if row and row["total"] is not None else 0.0

    def calculate_vacation_summary(
        self, year: int, records: list[VacationRecord] | None = None
    ) -> VacationSummary:
        """
        Calculates vacation totals for a year:
          - allowance: from settings
          - carry_over: total carry_over credit records in vacation_record
          - total_pool: allowance + carry_over
          - used: total annual_leave, public_holiday, special_leave records
          - remaining: total_pool - used

        If `records` is omitted, the full year's records are fetched
        internally via get_records_for_year() -- the same row-fetch method
        (and malformed-row-skip behavior) every other caller uses. If the
        caller already fetched the year's records itself (e.g. VacationTab
        building both the balance summary and the record tree from one
        fetch per refresh), pass them in here to skip the redundant fetch.
        Both branches sum over the same VacationRecord objects, so a
        malformed row is skipped consistently regardless of which path is
        used.
        """
        settings = self.get_settings(year)
        allowance = settings["hours_per_year"] if settings else 0.0

        if records is None:
            records = self.get_records_for_year(year)

        carry_over = sum(r.hours for r in records if r.vtype == VacationType.CARRY_OVER)
        used = sum(
            r.hours
            for r in records
            if r.vtype
            in (
                VacationType.ANNUAL_LEAVE,
                VacationType.PUBLIC_HOLIDAY,
                VacationType.SPECIAL_LEAVE,
            )
        )

        return VacationSummary(
            allowance=allowance,
            carry_over=carry_over,
            used=used,
        )

    def calculate_carry_over_allowance(self, to_year: int) -> CarryOverAllowance:
        """
        Calculates the remaining carry-over hours available from the
        previous year (to_year - 1) taking into account:
          - previous year's total pool (allowance + carry_over)
          - previous year's total used (annual, holiday, special)
          - previous year's unused surplus (total_pool - used)
          - maximum carry over limit for to_year
          - already transferred hours from prev_year to to_year
        """
        prev_year = to_year - 1
        prev_summary = self.calculate_vacation_summary(prev_year)

        surplus = prev_summary.remaining
        if surplus < 0:
            surplus = 0.0

        settings = self.get_settings(to_year)
        max_carry_over = settings["max_carry_over"] if settings else 0.0

        already_transferred = self.get_already_transferred(prev_year, to_year)

        return CarryOverAllowance(
            prev_surplus=surplus,
            max_carry_over=max_carry_over,
            already_transferred=already_transferred,
        )

    def get_work_day_targets(self) -> dict[int, float]:
        """Returns dict mapping day_of_week (0=Mon..6=Sun) to configured hours."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT day_of_week, hours FROM work_day_target;")
            return {row["day_of_week"]: row["hours"] for row in cursor.fetchall()}

    def get_date_exception(self, d: date) -> float | None:
        """Returns the exception hours for date d, or None if not configured."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT hours FROM work_day_exception WHERE date = ?;",
                (date_to_iso(d),),
            )
            row = cursor.fetchone()
            return row["hours"] if row else None

    def get_daily_target_for_date(self, d: date) -> float:
        """Returns the target hours for date d: a date exception takes priority,
        otherwise falls back to the weekday-based target (8.0 if not configured)."""
        exception_hours = self.get_date_exception(d)
        if exception_hours is not None:
            return exception_hours
        targets = self.get_work_day_targets()
        return targets.get(d.weekday(), 8.0)

    def add_carry_over(self, from_year: int, to_year: int, hours: float) -> None:
        """
        Records a carry-over transfer:
          1. INSERT INTO carry_over_log
          2. INSERT INTO vacation_record as 'carry_over' type
        Uses a transaction.
        """
        # Carry-over date is traditionally Jan 1st of destination year
        carry_date = f"{to_year:04d}-01-01"

        with self.db.connection() as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO carry_over_log (from_year, to_year, hours)
                    VALUES (?, ?, ?);
                    """,
                    (from_year, to_year, hours),
                )
                conn.execute(
                    """
                    INSERT INTO vacation_record (date, hours, vtype, note)
                    VALUES (?, ?, 'carry_over', ?);
                    """,
                    (carry_date, hours, f"Carry-over from {from_year}"),
                )
            self.bus.publish(Event.VACATION_CHANGED)
