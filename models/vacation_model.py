"""Model for vacation records: DB row/dataclass mapping and CRUD."""

import json
import logging
import sqlite3
from datetime import date, datetime
from typing import Any

from core.events import Event, EventBus
from core.timeutil import date_to_iso, iso_to_date, period_bounds
from db.database import Database
from domain.enums import RecordAction, RecordEntity, VacationType
from domain.types import (
    CarryOverAllowance,
    CarryOverLogEntry,
    VacationGrant,
    VacationRecord,
    VacationSummary,
)
from models._row_mapping import rows_to_records
from models.errors import raise_if_no_rows

# app_config key holding the maximum hours a year may borrow forward from the
# next year's pool. Stored JSON-serialized via SettingsManager; default 0.0
# (no borrowing) preserves the pre-#47 balance behaviour exactly.
_MAX_BORROW_HOURS_KEY = "vacation.max_borrow_hours"

_DEBIT_VACATION_TYPES = (
    VacationType.ANNUAL_LEAVE,
    VacationType.PUBLIC_HOLIDAY,
    VacationType.SPECIAL_LEAVE,
)

logger = logging.getLogger(__name__)


class VacationModel:  # pylint: disable=too-many-public-methods
    # This model owns two parallel record families (vacation records AND
    # ad-hoc grants), each with its own get/get-by-id/insert/update/delete
    # surface, plus the settings/carry-over/borrow accessors — one method
    # over pylint's default 20 (#47 added grant CRUD + get_max_borrow_hours).
    # The methods are cohesive, not a god-object; splitting the grant CRUD
    # into a second model would fragment a single table-owning boundary.
    """Manages vacation records, grants, allowance settings, and carry-over."""

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
                charge_rate=row["charge_rate"],
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
                    INSERT INTO vacation_record
                        (date, hours, vtype, note, charge_rate)
                    VALUES (?, ?, ?, ?, ?);
                    """,
                    (
                        date_to_iso(record.date),
                        record.hours,
                        record.vtype.value,
                        record.note,
                        record.charge_rate,
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
                        charge_rate = ?, updated_at = datetime('now')
                    WHERE id = ?;
                    """,
                    (
                        date_to_iso(record.date),
                        record.hours,
                        record.vtype.value,
                        record.note,
                        record.charge_rate,
                        record.id,
                    ),
                )
                raise_if_no_rows(
                    cursor,
                    RecordEntity.VACATION_RECORD,
                    record.id,
                    RecordAction.UPDATE,
                )
            self.bus.publish(Event.VACATION_CHANGED)

    def delete_record(self, record_id: int) -> None:
        """Deletes the vacation record with the given id."""
        with self.db.connection() as conn:
            with conn:
                cursor = conn.execute(
                    "DELETE FROM vacation_record WHERE id = ?;", (record_id,)
                )
                raise_if_no_rows(
                    cursor,
                    RecordEntity.VACATION_RECORD,
                    record_id,
                    RecordAction.DELETE,
                )
            self.bus.publish(Event.VACATION_CHANGED)

    # --- Vacation Grant CRUD ---
    #
    # Grants reuse RecordEntity.VACATION_RECORD for their RecordNotFoundError
    # staleness reporting rather than adding a dedicated enum member: the
    # user-facing "this record no longer exists" wording is identical, and
    # keeping the enum untouched minimizes blast radius (per the #47 contract).

    def _grant_row_to_record(self, row: sqlite3.Row) -> VacationGrant | None:
        """Builds a VacationGrant from a DB row, or None (with a logged
        warning) if the row violates a VacationGrant invariant -- e.g. a
        non-positive hours value added directly to the DB. Mirrors
        _row_to_record(): without this guard a single malformed row would
        raise out of every read method and take down the whole query."""
        try:
            return VacationGrant(
                id=row["id"],
                date=iso_to_date(row["date"]),
                hours=row["hours"],
                note=row["note"],
            )
        except (ValueError, TypeError):  # fmt: skip
            logger.warning(
                "Skipping malformed vacation_grant row: id=%r date=%r",
                row["id"],
                row["date"],
            )
            return None

    def get_grant_by_id(self, grant_id: int) -> VacationGrant | None:
        """Returns the vacation grant with the given id, or None if not found."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM vacation_grant WHERE id = ?;", (grant_id,))
            row = cursor.fetchone()
            return self._grant_row_to_record(row) if row else None

    def get_grants_for_year(self, year: int) -> list[VacationGrant]:
        """Returns all vacation grants dated within the given year, ordered by
        date DESC. Malformed rows are skipped (and counted in
        last_skipped_count), mirroring get_records_for_year()."""
        start_date, end_date = period_bounds(year, None)
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM vacation_grant WHERE date >= ? AND date <= ? "
                "ORDER BY date DESC;",
                (start_date, end_date),
            )
            rows = cursor.fetchall()
        grants, self.last_skipped_count = rows_to_records(
            rows, self._grant_row_to_record
        )
        return grants

    def insert_grant(self, grant: VacationGrant) -> int:
        """Inserts a new vacation grant and returns its id."""
        with self.db.connection() as conn:
            with conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO vacation_grant (date, hours, note)
                    VALUES (?, ?, ?);
                    """,
                    (
                        date_to_iso(grant.date),
                        grant.hours,
                        grant.note,
                    ),
                )
                grant_id = cursor.lastrowid or 0
            self.bus.publish(Event.VACATION_CHANGED)
            return grant_id

    def update_grant(self, grant: VacationGrant) -> None:
        """Updates an existing vacation grant identified by its id."""
        if grant.id is None:
            raise ValueError("Cannot update a grant without an ID.")
        with self.db.connection() as conn:
            with conn:
                cursor = conn.execute(
                    """
                    UPDATE vacation_grant
                    SET date = ?, hours = ?, note = ?,
                        updated_at = datetime('now')
                    WHERE id = ?;
                    """,
                    (
                        date_to_iso(grant.date),
                        grant.hours,
                        grant.note,
                        grant.id,
                    ),
                )
                raise_if_no_rows(
                    cursor,
                    RecordEntity.VACATION_RECORD,
                    grant.id,
                    RecordAction.UPDATE,
                )
            self.bus.publish(Event.VACATION_CHANGED)

    def delete_grant(self, grant_id: int) -> None:
        """Deletes the vacation grant with the given id."""
        with self.db.connection() as conn:
            with conn:
                cursor = conn.execute(
                    "DELETE FROM vacation_grant WHERE id = ?;", (grant_id,)
                )
                raise_if_no_rows(
                    cursor,
                    RecordEntity.VACATION_RECORD,
                    grant_id,
                    RecordAction.DELETE,
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
        self,
        year: int,
        records: list[VacationRecord] | None = None,
        _apply_borrow_prev: bool = True,
    ) -> VacationSummary:
        """
        Calculates vacation totals for a year:
          - allowance: from settings
          - carry_over: total carry_over credit records (NOT charge-weighted)
          - extra_grant: total of the year's ad-hoc VacationGrant hours
          - base_pool: allowance + carry_over + extra_grant
          - used: CHARGE-WEIGHTED sum(hours * charge_rate) over debit records
          - borrowed_prev: hours the previous year borrowed forward from this
            year's pool (see below)
          - total_pool: base_pool - borrowed_prev
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

        Borrowing (`_apply_borrow_prev`): when a non-zero
        `vacation.max_borrow_hours` is configured, a year whose usage exceeds
        its own base pool is allowed to "borrow" the overage (capped at
        max_borrow_hours) from the *next* year. This method computes
        `borrowed_prev` for `year` by recursing into `year - 1` with
        `_apply_borrow_prev=False`, which bounds the recursion to exactly ONE
        hop: borrowing propagates exactly one year forward and multi-year
        borrow chains are intentionally out of scope. When max_borrow_hours
        is 0 (the default) `borrowed_prev` is always 0, so total_pool reduces
        to `base_pool` (allowance + carry_over + extra_grant) and the
        pre-borrow behaviour is preserved exactly. The `_apply_borrow_prev`
        parameter is private (leading underscore) — external callers always
        want the borrow-aware result.
        """
        settings = self.get_settings(year)
        allowance = settings["hours_per_year"] if settings else 0.0

        if records is None:
            records = self.get_records_for_year(year)

        # get_grants_for_year() and the borrow recursion below each overwrite
        # self.last_skipped_count with their own (grants / other-year) skip
        # counts. core/report.py reads last_skipped_count right after this call
        # expecting THIS year's malformed-record skip count (the documented
        # "read it right after the fetch" contract), so snapshot it here --
        # after the records fetch, or the caller-supplied value when records
        # was passed in -- and restore it before returning.
        records_skipped = self.last_skipped_count

        carry_over = sum(r.hours for r in records if r.vtype == VacationType.CARRY_OVER)
        extra_grant = sum(g.hours for g in self.get_grants_for_year(year))
        used = sum(
            r.hours * r.charge_rate for r in records if r.vtype in _DEBIT_VACATION_TYPES
        )

        borrowed_prev = 0.0
        if _apply_borrow_prev:
            max_borrow = self.get_max_borrow_hours()
            if max_borrow > 0:
                prev = self.calculate_vacation_summary(
                    year - 1, _apply_borrow_prev=False
                )
                overage = max(0.0, prev.used - prev.base_pool)
                borrowed_prev = min(overage, max_borrow)

        self.last_skipped_count = records_skipped
        return VacationSummary(
            allowance=allowance,
            carry_over=carry_over,
            extra_grant=extra_grant,
            used=used,
            borrowed_prev=borrowed_prev,
        )

    def get_max_borrow_hours(self) -> float:
        """Returns the configured maximum borrow-forward hours (app_config key
        `vacation.max_borrow_hours`), or 0.0 if unset/malformed.

        Reads app_config directly (JSON-parsing the stored value) rather than
        going through SettingsManager, consistent with get_settings() and the
        other direct-SELECT accessors on this model. A malformed/non-numeric
        stored value falls back to 0.0 — the same no-borrow default as an
        absent key — so a corrupt setting can never widen the borrow cap."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT value FROM app_config WHERE key = ?;",
                (_MAX_BORROW_HOURS_KEY,),
            )
            row = cursor.fetchone()
        if not row:
            return 0.0
        try:
            value = float(json.loads(row["value"]))
        except ValueError, TypeError, json.JSONDecodeError:
            logger.warning(
                "Malformed %s app_config value %r; defaulting to 0.0",
                _MAX_BORROW_HOURS_KEY,
                row["value"],
            )
            return 0.0
        return max(0.0, value)

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
