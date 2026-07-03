"""Tests for pure, Tk-free helper functions in views/time_clock_tab.py.

``_build_exc_dict`` does not touch tkinter at all (no widget construction),
so it can be exercised directly without a live Tk interpreter or display —
unlike the rest of the module, which this repo's CI (headless, no X
display) cannot instantiate. See tests/views/test_report_dialog.py and
tests/views/test_help_viewer_dialogs.py for the same headless-CI
constraint on the other view modules.

Note: malformed-*date* handling now lives in
models/time_clock_model.py:get_date_exceptions() (WorkDayException.date is
a real `date` object by the time it reaches this view layer — see
tests/models/test_time_clock_model.py for that coverage).
``_build_exc_dict`` only needs to guard against a malformed *hours* value.
"""
import logging
from datetime import date

from domain.types import WorkDayException
from views.time_clock_tab import _build_exc_dict


def test_build_exc_dict_parses_valid_rows() -> None:
    raw = [
        WorkDayException(id=1, date=date(2026, 6, 1), hours=4.0, label="Half day"),
        WorkDayException(id=2, date=date(2026, 6, 2), hours=0.0, label="Day off"),
    ]
    result = _build_exc_dict(raw)
    assert result == {
        date(2026, 6, 1): 4.0,
        date(2026, 6, 2): 0.0,
    }


def test_build_exc_dict_skips_malformed_hours_and_logs_warning(caplog) -> None:
    raw = [WorkDayException(id=1, date=date(2026, 6, 1), hours="not-a-number", label=None)]  # type: ignore[arg-type]

    with caplog.at_level(logging.WARNING, logger="views.time_clock_tab"):
        result = _build_exc_dict(raw)

    assert result == {}
    assert len(caplog.records) == 1
