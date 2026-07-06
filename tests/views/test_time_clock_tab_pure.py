"""Tests for pure, Tk-free helper functions in views/time_clock_tab.py.

``_build_exc_dict`` does not touch tkinter at all (no widget construction),
so it can be exercised directly without a live Tk interpreter or display —
unlike the rest of the module, which this repo's CI (headless, no X
display) cannot instantiate. See tests/views/test_report_dialog.py and
tests/views/test_help_viewer_dialogs.py for the same headless-CI
constraint on the other view modules.

Note: malformed-*date* and malformed-*hours* handling both now live in
models/time_clock_model.py:get_date_exceptions() — WorkDayException itself
enforces hours >= 0 (domain/types.py) and raises ValueError for a
non-numeric or negative value, and get_date_exceptions() catches that (like
it already did for a malformed date) and skips the row with a logged
warning before it ever reaches this view layer. So a real WorkDayException
reaching _build_exc_dict always has a valid `date` and `hours` by
construction — see tests/models/test_time_clock_model.py for that
model-layer coverage. The malformed-hours tests below use a bare
`SimpleNamespace` stand-in (not a real WorkDayException, which can no
longer hold a malformed value) purely to exercise _build_exc_dict's own
defense-in-depth guard.
"""

import logging
from datetime import date
from types import SimpleNamespace

from domain.types import WorkDayException
from views.time_clock_tab import _build_exc_dict


def test_build_exc_dict_parses_valid_rows() -> None:
    raw = [
        WorkDayException(id=1, date=date(2026, 6, 1),
                         hours=4.0, label="Half day"),
        WorkDayException(id=2, date=date(2026, 6, 2),
                         hours=0.0, label="Day off"),
    ]
    result = _build_exc_dict(raw)
    assert result == {
        date(2026, 6, 1): 4.0,
        date(2026, 6, 2): 0.0,
    }


def test_build_exc_dict_skips_malformed_hours_and_logs_warning(caplog) -> None:
    """A real WorkDayException can no longer hold a non-numeric `hours`
    (domain/types.py's __post_init__ rejects it at construction, and
    get_date_exceptions() skips such a row before it reaches this view
    layer). This uses a duck-typed stand-in to exercise _build_exc_dict's
    own defense-in-depth guard directly."""
    raw = [SimpleNamespace(date=date(2026, 6, 1), hours="not-a-number")]

    with caplog.at_level(logging.WARNING, logger="views.time_clock_tab"):
        result = _build_exc_dict(raw)

    assert result == {}
    assert len(caplog.records) == 1


def test_build_exc_dict_skips_none_hours_and_logs_warning(caplog) -> None:
    """Same as above for `hours=None` (float(None) raises TypeError, which
    _build_exc_dict must also catch, not just the malformed-string
    ValueError case above)."""
    raw = [SimpleNamespace(date=date(2026, 6, 1), hours=None)]

    with caplog.at_level(logging.WARNING, logger="views.time_clock_tab"):
        result = _build_exc_dict(raw)

    assert result == {}
    assert len(caplog.records) == 1
