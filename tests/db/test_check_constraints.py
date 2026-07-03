"""Tests asserting SQLite-level CHECK constraints from `_create_tables()`.

`domain/types.py` dataclasses' `__post_init__` enforces some of these same
invariants at the Python layer, but the DB-level CHECK constraints are the
last line of defense for anything that bypasses the dataclass/model layer
(a raw SQL insert, or a bug in a model's insert method that builds SQL by
hand instead of going through the dataclass). These tests connect directly
via `db.get_connection()` and issue raw INSERT statements that violate each
constraint, bypassing the model/controller layer entirely, to prove the
constraints themselves — not just the Python-side validation — are in place.
"""

import sqlite3

import pytest

from db.database import Database


def test_time_record_work_type_check_rejects_invalid_value(db: Database) -> None:
    conn = db.get_connection()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO time_record (date, start_time, work_type) "
            "VALUES ('2026-01-01', '09:00', 'not_a_work_type');"
        )


def test_time_record_work_type_check_accepts_all_valid_values(db: Database) -> None:
    conn = db.get_connection()
    for i, work_type in enumerate(("in_site", "road", "remote")):
        conn.execute(
            "INSERT INTO time_record (date, start_time, work_type) VALUES (?, ?, ?);",
            (f"2026-01-0{i + 1}", "09:00", work_type),
        )
    count = conn.execute("SELECT COUNT(*) FROM time_record;").fetchone()[0]
    assert count == 3


@pytest.mark.parametrize(
    ("table", "columns", "values"),
    [
        pytest.param(
            "work_day_target",
            "(day_of_week, hours)",
            (0, -1.0),
            id="work_day_target-hours>=0",
        ),
        pytest.param(
            "work_day_exception",
            "(date, hours)",
            ("2026-01-01", -0.5),
            id="work_day_exception-hours>=0",
        ),
        pytest.param(
            "vacation_record",
            "(date, hours, vtype)",
            ("2026-01-01", -1.0, "annual_leave"),
            id="vacation_record-hours>=0-post-v2-relaxation",
        ),
    ],
)
def test_hours_check_rejects_negative_on_hours_gte_zero_tables(
    db: Database, table: str, columns: str, values: tuple
) -> None:
    """These tables use CHECK(hours >= 0) — negative values must be rejected,
    but a boundary value of exactly 0 must NOT be (that boundary is exercised
    separately, since it's the whole point of vacation_record's v2 migration)."""
    conn = db.get_connection()
    placeholders = ", ".join("?" for _ in values)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(f"INSERT INTO {table} {columns} VALUES ({placeholders});", values)


@pytest.mark.parametrize(
    ("table", "columns", "values"),
    [
        pytest.param(
            "sickness_record",
            "(date, hours)",
            ("2026-01-01", 0.0),
            id="sickness_record-hours>0-zero-rejected",
        ),
        pytest.param(
            "carry_over_log",
            "(from_year, to_year, hours)",
            (2025, 2026, 0.0),
            id="carry_over_log-hours>0-zero-rejected",
        ),
    ],
)
def test_hours_check_rejects_zero_on_hours_gt_zero_tables(
    db: Database, table: str, columns: str, values: tuple
) -> None:
    """Unlike the CHECK(hours >= 0) tables above, these tables use the
    strictly-greater CHECK(hours > 0) — a boundary value of exactly 0 must
    be rejected too, not just negative values."""
    conn = db.get_connection()
    placeholders = ", ".join("?" for _ in values)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(f"INSERT INTO {table} {columns} VALUES ({placeholders});", values)


def test_vacation_record_hours_zero_is_accepted_after_v2_relaxation(
    db: Database,
) -> None:
    """The whole point of the version-2 migration: hours=0 must be accepted
    on vacation_record (unlike the CHECK(hours > 0) tables above), to support
    0-hour public-holiday imports."""
    conn = db.get_connection()
    conn.execute(
        "INSERT INTO vacation_record (date, hours, vtype) "
        "VALUES ('2026-01-01', 0.0, 'public_holiday');"
    )
    count = conn.execute("SELECT COUNT(*) FROM vacation_record;").fetchone()[0]
    assert count == 1


def test_miliuim_period_check_rejects_end_date_before_start_date(db: Database) -> None:
    conn = db.get_connection()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO miliuim_period (start_date, end_date) "
            "VALUES ('2026-06-10', '2026-06-01');"
        )


def test_miliuim_period_check_accepts_end_date_equal_to_start_date(
    db: Database,
) -> None:
    """end_date >= start_date (not strictly >) — a single-day period must
    be allowed."""
    conn = db.get_connection()
    conn.execute(
        "INSERT INTO miliuim_period (start_date, end_date) "
        "VALUES ('2026-06-10', '2026-06-10');"
    )
    count = conn.execute("SELECT COUNT(*) FROM miliuim_period;").fetchone()[0]
    assert count == 1


@pytest.mark.parametrize("day_of_week", [-1, 7], ids=["below-range", "above-range"])
def test_work_day_target_check_rejects_out_of_range_day_of_week(
    db: Database, day_of_week: int
) -> None:
    conn = db.get_connection()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO work_day_target (day_of_week, hours) VALUES (?, 8.0);",
            (day_of_week,),
        )


@pytest.mark.parametrize("day_of_week", [0, 6], ids=["monday", "sunday"])
def test_work_day_target_check_accepts_boundary_day_of_week(
    db: Database, day_of_week: int
) -> None:
    conn = db.get_connection()
    conn.execute(
        "INSERT INTO work_day_target (day_of_week, hours) VALUES (?, 8.0);",
        (day_of_week,),
    )
    row = conn.execute(
        "SELECT hours FROM work_day_target WHERE day_of_week = ?;", (day_of_week,)
    ).fetchone()
    assert row["hours"] == 8.0
