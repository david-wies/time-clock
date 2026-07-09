"""Tests for domain/enums.py's WarningCode.blocking metadata and the
controller-level helper that consumes it.

WarningCode.blocking exists to let callers decide whether a validation code
belongs in Result.errors (blocking) or Result.warnings (non-blocking),
without each call site hand-rolling the same distinction. See
controllers/time_clock_controller.py's `_is_blocking()`.
"""

from controllers.time_clock_controller import _is_blocking
from domain.enums import WarningCode

# ─────────────────────────── WarningCode.blocking ─────────────────────────────


def test_overnight_shift_is_non_blocking() -> None:
    assert WarningCode.OVERNIGHT_SHIFT.blocking is False


def test_open_record_exists_is_blocking() -> None:
    assert WarningCode.OPEN_RECORD_EXISTS.blocking is True


def test_multiple_open_records_is_blocking() -> None:
    assert WarningCode.MULTIPLE_OPEN_RECORDS.blocking is True


def test_over_balance_is_blocking() -> None:
    assert WarningCode.OVER_BALANCE.blocking is True


def test_only_overnight_shift_is_non_blocking() -> None:
    """OVERNIGHT_SHIFT must remain the only non-blocking WarningCode member
    — every other member is blocking."""
    non_blocking = [code for code in WarningCode if not code.blocking]
    assert non_blocking == [WarningCode.OVERNIGHT_SHIFT]


# ─────────────────────── _is_blocking() (controller helper) ───────────────────


def test_is_blocking_matches_warning_code_blocking_flag() -> None:
    for code in WarningCode:
        assert _is_blocking(code.value) is code.blocking


def test_is_blocking_treats_unrecognized_string_as_blocking() -> None:
    """Free-text errors (e.g. the overlap message from validate_time_record())
    are not recognized WarningCode values, so they must default to
    blocking."""
    assert _is_blocking("Record overlaps with an existing time record.") is True


def test_is_blocking_filters_mixed_code_list_correctly() -> None:
    """A mixed list of blocking and non-blocking codes filters down to only
    the blocking ones, mirroring the three call sites in
    TimeClockController (save_record, clock_in, clock_out)."""
    errors = [
        WarningCode.OVERNIGHT_SHIFT.value,
        "Record overlaps with an existing time record.",
        WarningCode.OPEN_RECORD_EXISTS.value,
    ]

    blocking = [e for e in errors if _is_blocking(e)]

    assert blocking == [
        "Record overlaps with an existing time record.",
        WarningCode.OPEN_RECORD_EXISTS.value,
    ]
