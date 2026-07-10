"""Tests for `_parse_exception_hours` in views/settings_dialog.py.

This is a plain, Tk-free helper function (no widget construction), so it can
be exercised directly without a live Tk interpreter or display — unlike the
rest of the module, which this repo's CI (headless, no X display) cannot
instantiate. See tests/views/test_time_clock_tab_pure.py and
tests/views/test_report_dialog.py for the same headless-CI constraint on
other view modules.
"""

import pytest

from views.settings_dialog import _parse_exception_hours


def test_parse_exception_hours_accepts_value_in_range() -> None:
    assert _parse_exception_hours("4.5") == 4.5


def test_parse_exception_hours_accepts_lower_bound() -> None:
    assert _parse_exception_hours("0") == 0.0


def test_parse_exception_hours_accepts_upper_bound() -> None:
    assert _parse_exception_hours("24") == 24.0


def test_parse_exception_hours_rejects_non_numeric() -> None:
    with pytest.raises(ValueError, match="Hours must be a number."):
        _parse_exception_hours("abc")


def test_parse_exception_hours_rejects_negative() -> None:
    with pytest.raises(ValueError, match="Hours must be between 0 and 24."):
        _parse_exception_hours("-1")


def test_parse_exception_hours_rejects_above_max() -> None:
    with pytest.raises(ValueError, match="Hours must be between 0 and 24."):
        _parse_exception_hours("24.5")
