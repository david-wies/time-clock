import sqlite3
from datetime import date, datetime
from typing import Optional, Any
from domain.types import VacationRecord, VacationSummary, CarryOverAllowance, CarryOverLogEntry
from domain.enums import VacationType
from core.events import EventBus, Event
from core.timeutil import iso_to_date, date_to_iso
from db.database import Database


class VacationModel:
    def __init__(self, db: Database, bus: EventBus) -> None:
        self.db = db
        self.bus = bus

    def _row_to_record(self, row: sqlite3.Row) -> VacationRecord:
        return VacationRecord(
            id=row["id"],
            date=iso_to_date(row["date"]),
            hours=row["hours"],
            vtype=VacationType(row["vtype"]),
            note=row["note"]
        )

    def get_record_by_id(self, record_id: int) -> Optional[VacationRecord]:
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM vacation_record WHERE id = ?;", (record_id,))
            row = cursor.fetchone()
            return self._row_to_record(row) if row else None
        finally:
            conn.close()

    def get_records_for_year(self, year: int, month: Optional[int] = None) -> list[VacationRecord]:
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            if month is not None:
                start_date = f"{year:04d}-{month:02d}-01"
                end_date = f"{year:04d}-{month:02d}-31"
                cursor.execute(
                    "SELECT * FROM vacation_record WHERE date >= ? AND date <= ? ORDER BY date DESC;",
                    (start_date, end_date)
                )
            else:
                start_date = f"{year:04d}-01-01"
                end_date = f"{year:04d}-12-31"
                cursor.execute(
                    "SELECT * FROM vacation_record WHERE date >= ? AND date <= ? ORDER BY date DESC;",
                    (start_date, end_date)
                )
            rows = cursor.fetchall()
            return [self._row_to_record(row) for row in rows]
        finally:
            conn.close()

    def insert_record(self, record: VacationRecord) -> int:
        conn = self.db.get_connection()
        try:
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
                        record.note
                    )
                )
                record_id = cursor.lastrowid or 0
            self.bus.publish(Event.VACATION_CHANGED)
            return record_id
        finally:
            conn.close()

    def update_record(self, record: VacationRecord) -> None:
        if record.id is None:
            raise ValueError("Cannot update a record without an ID.")
        conn = self.db.get_connection()
        try:
            with conn:
                conn.execute(
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
                        record.id
                    )
                )
            self.bus.publish(Event.VACATION_CHANGED)
        finally:
            conn.close()

    def delete_record(self, record_id: int) -> None:
        conn = self.db.get_connection()
        try:
            with conn:
                conn.execute(
                    "DELETE FROM vacation_record WHERE id = ?;", (record_id,))
            self.bus.publish(Event.VACATION_CHANGED)
        finally:
            conn.close()

    # --- Vacation Settings Queries ---

    def get_settings(self, year: int) -> Optional[dict[str, Any]]:
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT hours_per_year, max_carry_over FROM vacation_settings WHERE year = ?;", (year,))
            row = cursor.fetchone()
            if row:
                return {
                    "hours_per_year": row["hours_per_year"],
                    "max_carry_over": row["max_carry_over"]
                }
            return None
        finally:
            conn.close()

    def save_settings(self, year: int, hours_per_year: float, max_carry_over: float) -> None:
        conn = self.db.get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO vacation_settings (year, hours_per_year, max_carry_over)
                    VALUES (?, ?, ?);
                    """,
                    (year, hours_per_year, max_carry_over)
                )
            self.bus.publish(Event.SETTINGS_CHANGED)
        finally:
            conn.close()

    # --- Carry-Over Calculations & Logging ---

    def get_carry_over_history(self, to_year: int) -> list[CarryOverLogEntry]:
        """Returns list of carry-over log details for the destination year."""
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, from_year, to_year, hours, transferred_at FROM carry_over_log WHERE to_year = ?;", (to_year,))
            rows = cursor.fetchall()
            return [
                CarryOverLogEntry(
                    id=row["id"],
                    from_year=row["from_year"],
                    to_year=row["to_year"],
                    hours=row["hours"],
                    transferred_at=datetime.fromisoformat(
                        row["transferred_at"]),
                )
                for row in rows
            ]
        finally:
            conn.close()

    def get_already_transferred(self, from_year: int, to_year: int) -> float:
        """Returns sum of hours already transferred from from_year to to_year."""
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT SUM(hours) as total FROM carry_over_log WHERE from_year = ? AND to_year = ?;",
                (from_year, to_year)
            )
            row = cursor.fetchone()
            return row["total"] if row and row["total"] is not None else 0.0
        finally:
            conn.close()

    def calculate_vacation_summary(self, year: int) -> VacationSummary:
        """
        Calculates vacation totals for a year:
          - allowance: from settings
          - carry_over: total carry_over credit records in vacation_record
          - total_pool: allowance + carry_over
          - used: total annual_leave, public_holiday, special_leave records
          - remaining: total_pool - used
        """
        settings = self.get_settings(year)
        allowance = settings["hours_per_year"] if settings else 0.0

        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            # Carry-over credits and used debits in a single pass over the
            # table via conditional aggregation, instead of two sequential
            # SUM(...) queries over the same date range.
            cursor.execute(
                """
                SELECT
                    SUM(CASE WHEN vtype = 'carry_over' THEN hours ELSE 0 END) AS carry_over,
                    SUM(CASE WHEN vtype IN ('annual_leave', 'public_holiday', 'special_leave')
                        THEN hours ELSE 0 END) AS used
                FROM vacation_record
                WHERE date >= ? AND date <= ?;
                """,
                (f"{year:04d}-01-01", f"{year:04d}-12-31")
            )
            row = cursor.fetchone()
            carry_over = row["carry_over"] if row and row["carry_over"] is not None else 0.0
            used = row["used"] if row and row["used"] is not None else 0.0
        finally:
            conn.close()

        total_pool = allowance + carry_over
        remaining = total_pool - used

        return VacationSummary(
            allowance=allowance,
            carry_over=carry_over,
            total_pool=total_pool,
            used=used,
            remaining=remaining,
        )

    def calculate_carry_over_allowance(self, to_year: int) -> CarryOverAllowance:
        """
        Calculates the remaining carry-over hours available from the previous year (to_year - 1)
        taking into account:
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
        available_surplus = surplus - already_transferred
        if available_surplus < 0:
            available_surplus = 0.0

        allowed_transfer = min(
            max_carry_over - already_transferred, available_surplus)
        if allowed_transfer < 0:
            allowed_transfer = 0.0

        return CarryOverAllowance(
            prev_surplus=surplus,
            max_carry_over=max_carry_over,
            already_transferred=already_transferred,
            available_surplus=available_surplus,
            allowed_transfer=allowed_transfer,
        )

    def get_work_day_targets(self) -> dict[int, float]:
        """Returns dict mapping day_of_week (0=Mon..6=Sun) to configured hours."""
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT day_of_week, hours FROM work_day_target;")
            return {row["day_of_week"]: row["hours"] for row in cursor.fetchall()}
        finally:
            conn.close()

    def get_date_exception(self, d: date) -> Optional[float]:
        """Returns the exception hours configured for date d, or None if not configured."""
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT hours FROM work_day_exception WHERE date = ?;",
                (date_to_iso(d),)
            )
            row = cursor.fetchone()
            return row["hours"] if row else None
        finally:
            conn.close()

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

        conn = self.db.get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO carry_over_log (from_year, to_year, hours)
                    VALUES (?, ?, ?);
                    """,
                    (from_year, to_year, hours)
                )
                conn.execute(
                    """
                    INSERT INTO vacation_record (date, hours, vtype, note)
                    VALUES (?, ?, 'carry_over', ?);
                    """,
                    (carry_date, hours, f"Carry-over from {from_year}")
                )
            self.bus.publish(Event.VACATION_CHANGED)
        finally:
            conn.close()
