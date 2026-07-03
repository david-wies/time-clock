from __future__ import annotations

from datetime import date

from hdate import HebrewDate


def to_hebrew_label(d: date) -> str:
    """Returns a Hebrew calendar date string for d (e.g. 'י"ג תמוז ה' תשפ"ו')."""
    # Reverse string so tkinter's LTR-only rendering displays Hebrew RTL correctly.
    return str(HebrewDate.from_gdate(d))[::-1]
