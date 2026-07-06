"""Shared row-list-to-record-list mapping helper used by all models.

Each model owns its own `_row_to_record(row) -> RecordType | None` mapping
(the per-type logic differs), but the loop that applies it across a list of
rows, drops the malformed (None) results, and counts how many were skipped
is identical across models. That shared loop lives here.
"""

import sqlite3
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def rows_to_records(
    rows: list[sqlite3.Row], row_to_record: Callable[[sqlite3.Row], T | None]
) -> tuple[list[T], int]:
    """Maps each row via `row_to_record`, dropping rows that map to None.

    Returns `(records, skipped_count)` where `skipped_count` is the number
    of rows that `row_to_record` rejected as malformed.
    """
    records = []
    for row in rows:
        rec = row_to_record(row)
        if rec is not None:
            records.append(rec)
    return records, len(rows) - len(records)
