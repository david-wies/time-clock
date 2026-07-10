"""Direct unit tests for `times_overlap()` (controllers/time_clock_controller.py).

Only exercised indirectly elsewhere (via `validate_time_record`/`save_record`
integration tests in tests/controllers/test_time_clock_controller.py). These
tests call the function directly to pin its boundary semantics: adjacent
(back-to-back) intervals must NOT count as overlapping (the comparison is
strict `<`, not `<=`), two simultaneous open (still-clocked-in) records must
overlap via the function's own end-of-day `1440` sentinel, and an
overnight-wrapping interval must be compared correctly against a normal
same-day interval. A `<` -> `<=` regression in either comparison, or a
regression in the overnight-wrap handling, should cause at least one of
these to fail.
"""

from datetime import time

import pytest

from controllers.time_clock_controller import times_overlap


def test_back_to_back_same_day_is_not_overlap() -> None:
    """end1 == start2 (one shift ends exactly when the next starts) must NOT
    count as an overlap — adjacent-but-not-overlapping intervals are fine."""
    assert times_overlap(time(9, 0), time(17, 0), time(17, 0), time(18, 0)) is False


def test_back_to_back_same_day_is_not_overlap_reversed_argument_order() -> None:
    """The relation must be symmetric regardless of which interval is
    passed first."""
    assert times_overlap(time(17, 0), time(18, 0), time(9, 0), time(17, 0)) is False


def test_overlapping_intervals_sharing_one_minute_do_overlap() -> None:
    """One minute of genuine overlap (as opposed to exact back-to-back)
    must be detected — this is what would break if `<` regressed to `<=`
    in the *other* direction (over-permissive)."""
    assert times_overlap(time(9, 0), time(17, 1), time(17, 0), time(18, 0)) is True


def test_two_simultaneous_open_records_overlap() -> None:
    """Two records that are both still clocked in (end=None) must be
    treated as overlapping — an open record's implicit end is end-of-day
    (the function's own 1440-minute sentinel), so any two open records on
    the same day always overlap regardless of their start times."""
    assert times_overlap(time(9, 0), None, time(14, 0), None) is True


def test_two_simultaneous_open_records_with_identical_start_overlap() -> None:
    assert times_overlap(time(9, 0), None, time(9, 0), None) is True


def test_open_record_overlaps_a_later_closed_record_starting_before_midnight() -> None:
    """An open record starting at 09:00 (implicit end = 1440) must overlap
    any closed record later the same day."""
    assert times_overlap(time(9, 0), None, time(20, 0), time(21, 0)) is True


def test_overnight_shift_overlaps_nested_late_evening_record() -> None:
    """An overnight shift (start > end, e.g. 22:00 -> 02:00 the next day) is
    wrapped to end-of-day (1440) for same-day comparison purposes. A normal
    same-day record nested inside that wrapped span (23:00-23:30) must be
    detected as overlapping."""
    assert times_overlap(time(22, 0), time(2, 0), time(23, 0), time(23, 30)) is True


def test_overnight_shift_does_not_overlap_earlier_same_day_record() -> None:
    """A normal same-day record that finishes well before the overnight
    shift starts (08:00-09:00, vs. a 22:00 -> 02:00 overnight shift) must
    NOT be flagged as overlapping — the wrap only extends the overnight
    shift's *end* to midnight, it does not pull its start earlier."""
    assert times_overlap(time(22, 0), time(2, 0), time(8, 0), time(9, 0)) is False


def test_overnight_shift_starting_before_prior_wrapped_end_is_overlap() -> None:
    """Boundary case combining both semantics: an overnight shift wrapped
    to end at 1440, immediately followed (same calendar date) by another
    interval starting exactly at a time equal to the wrapped end (24:00 /
    time(0, 0) cannot be represented by `datetime.time`, so this instead
    pins the adjacent case at the wrap boundary using two overnight-shaped
    intervals starting back-to-back at 22:00 and ending past midnight)."""
    # First shift: 22:00 -> 01:00 (wraps to end1=1440 for comparison).
    # Second: 23:59 -> 00:30 — starts one minute before the first's
    # wrapped end, so this must be flagged as overlapping (not a boundary
    # case at all — included to confirm the wrap doesn't over-relax and
    # accidentally treat two overnight shifts on the same day as disjoint).
    assert times_overlap(time(22, 0), time(1, 0), time(23, 59), time(0, 30)) is True


@pytest.mark.parametrize(
    ("s1", "e1", "s2", "e2", "expected"),
    [
        pytest.param(
            time(9, 0),
            time(10, 0),
            time(10, 0),
            time(11, 0),
            False,
            id="back-to-back-morning",
        ),
        pytest.param(
            time(0, 0),
            time(1, 0),
            time(1, 0),
            time(2, 0),
            False,
            id="back-to-back-midnight-start",
        ),
    ],
)
def test_back_to_back_boundary_parametrized(
    s1: time, e1: time, s2: time, e2: time, expected: bool
) -> None:
    assert times_overlap(s1, e1, s2, e2) is expected
