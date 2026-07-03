"""Unit tests for core/hebrew_date.py.

to_hebrew_label() always returns a non-empty str.
"""

from datetime import date

import pytest

from core.hebrew_date import to_hebrew_label

# Hebrew Unicode block (Basic Hebrew: U+0590–U+05FF).
# Labels must contain at least one character in this range.
_HEBREW_BLOCK_START = 0x0590
_HEBREW_BLOCK_END = 0x05FF


def _has_hebrew_chars(text: str) -> bool:
    """Returns True if *text* contains at least one Hebrew-block Unicode character."""
    return any(_HEBREW_BLOCK_START <= ord(c) <= _HEBREW_BLOCK_END for c in text)


# ─────────────── Return-type guarantees ──────────────────────────────────────


@pytest.mark.parametrize(
    "d",
    [
        date(2026, 1, 1),  # Tevet 5786
        date(2026, 3, 15),  # Adar 5786
        date(2026, 6, 26),  # 1 Tammuz 5786
        date(2026, 9, 22),  # Tishrei 5787 (Rosh Hashana)
        date(2026, 12, 31),  # Tevet 5787
        date(2025, 9, 22),  # Rosh Hashana 5786
        date(2024, 3, 7),  # Adar II 5784 (Hebrew leap year)
    ],
    ids=[
        "tevet-5786",
        "adar-5786",
        "tammuz-5786",
        "tishrei-5787",
        "tevet-5787",
        "rosh-hashana-5786",
        "adar2-5784",
    ],
)
def test_to_hebrew_label_returns_nonempty_str(d):
    label = to_hebrew_label(d)
    assert isinstance(label, str)
    assert len(label) > 0
    assert label is not None


# ─────────────── Hebrew character content ────────────────────────────────────


@pytest.mark.parametrize(
    "d",
    [
        date(2026, 1, 1),
        date(2026, 6, 26),
        date(2025, 9, 22),
    ],
    ids=["tevet", "tammuz", "rosh-hashana"],
)
def test_to_hebrew_label_contains_hebrew_characters(d):
    label = to_hebrew_label(d)
    assert _has_hebrew_chars(label), (
        f"Expected Hebrew characters in label {label!r} for date {d}"
    )


# ─────────────── Labels differ across dates ───────────────────────────────────


def test_to_hebrew_label_differs_between_dates_same_year():
    # June and January of the same Gregorian year fall in different Hebrew months.
    label_june = to_hebrew_label(date(2026, 6, 26))
    label_jan = to_hebrew_label(date(2026, 1, 1))
    assert label_june != label_jan


def test_to_hebrew_label_differs_between_years():
    # The same calendar day in consecutive years has a different Hebrew date.
    label_2026 = to_hebrew_label(date(2026, 6, 26))
    label_2025 = to_hebrew_label(date(2025, 6, 26))
    assert label_2026 != label_2025


def test_to_hebrew_label_differs_consecutive_days():
    label_day1 = to_hebrew_label(date(2026, 6, 26))
    label_day2 = to_hebrew_label(date(2026, 6, 27))
    assert label_day1 != label_day2


# ─────────────── Consistency ─────────────────────────────────────────────────


def test_to_hebrew_label_same_date_twice_is_idempotent():
    d = date(2026, 6, 26)
    assert to_hebrew_label(d) == to_hebrew_label(d)
