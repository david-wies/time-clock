"""Tests for pure, Tk-free helper functions in views/time_clock_tab.py.

``_build_exc_dict`` does not touch tkinter at all (no widget construction),
so it can be exercised directly without a live Tk interpreter or display —
unlike the rest of the module, which this repo's CI (headless, no X
display) cannot instantiate. See tests/views/test_report_dialog.py and
tests/views/test_help_viewer_dialogs.py for the same headless-CI
constraint on the other view modules.
"""
import logging
from datetime import date

from domain.types import WorkDayException
from views.time_clock_tab import _build_exc_dict


def test_build_exc_dict_parses_valid_rows() -> None:
    raw = [
        WorkDayException(id=1, date="2026-06-01", hours=4.0, label="Half day"),
        WorkDayException(id=2, date="2026-06-02", hours=0.0, label="Day off"),
    ]
    result = _build_exc_dict(raw)
    assert result == {
        date(2026, 6, 1): 4.0,
        date(2026, 6, 2): 0.0,
    }


def test_build_exc_dict_skips_malformed_date_and_logs_warning(
        caplog) -> None:
    raw = [
        WorkDayException(id=1, date="2026-06-01", hours=4.0, label=None),
        WorkDayException(id=2, date="not-a-date", hours=8.0, label=None),
    ]
    with caplog.at_level(logging.WARNING, logger="views.time_clock_tab"):
        result = _build_exc_dict(raw)

    # The malformed row is silently dropped from the resulting dict (falls
    # back to the regular weekly target for that date)...
    assert result == {date(2026, 6, 1): 4.0}
    # ...but it must no longer be silent in the log (previously only a
    # stderr print with no logging framework hook).
    assert any(
        record.levelname == "WARNING" and "malformed" in record.message.lower()
        for record in caplog.records
    )


def test_build_exc_dict_skips_malformed_hours_and_logs_warning(caplog) -> None:
    raw = [WorkDayException(id=1, date="2026-06-01", hours="not-a-number", label=None)]  # type: ignore[arg-type]

    with caplog.at_level(logging.WARNING, logger="views.time_clock_tab"):
        result = _build_exc_dict(raw)

    assert result == {}
    assert len(caplog.records) == 1
