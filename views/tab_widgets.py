"""Reusable widget-building blocks shared by the record-list tabs
(VacationTab, MiliuimTab, SicknessTab, TimeClockTab)."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from datetime import date
from tkinter import ttk

from core.timeutil import MONTH_NAMES


def build_year_month_filter_bar(
    parent: tk.Widget,
    selected_year: int,
    on_change: Callable[[object], None],
) -> tuple[tk.StringVar, tk.StringVar, ttk.Combobox, ttk.Combobox]:
    """Builds the "Year: [combo]  Month: [combo]" filter row.

    Month values include a leading "All" entry; returns the (var_year,
    var_month, cbo_year, cbo_month) widgets so the caller can store them.
    """
    filter_bar = ttk.Frame(parent)
    filter_bar.pack(fill="x", padx=4, pady=(4, 0))

    ttk.Label(filter_bar, text="Year:").pack(side="left")
    cur_year = date.today().year
    var_year = tk.StringVar(value=str(selected_year))
    cbo_year = ttk.Combobox(
        filter_bar,
        textvariable=var_year,
        width=6,
        values=[str(y) for y in range(cur_year - 10, cur_year + 3)],
        state="readonly",
    )
    cbo_year.pack(side="left", padx=(2, 10))
    cbo_year.bind("<<ComboboxSelected>>", on_change)

    ttk.Label(filter_bar, text="Month:").pack(side="left")
    var_month = tk.StringVar(value="All")
    cbo_month = ttk.Combobox(
        filter_bar,
        textvariable=var_month,
        width=11,
        values=["All"] + MONTH_NAMES[1:],
        state="readonly",
    )
    cbo_month.pack(side="left", padx=(2, 0))
    cbo_month.bind("<<ComboboxSelected>>", on_change)

    return var_year, var_month, cbo_year, cbo_month


def build_action_bar(parent: tk.Widget) -> ttk.Frame:
    """Builds the separator + inner button row a CRUD action bar sits in."""
    action_bar = ttk.Frame(parent)
    action_bar.pack(fill="x", padx=4, pady=(0, 6))
    ttk.Separator(action_bar, orient="horizontal").pack(fill="x", pady=(0, 6))
    inner = ttk.Frame(action_bar)
    inner.pack(fill="x")
    return inner


def build_add_edit_remove_buttons(
    parent: tk.Widget,
    on_add: Callable[[], None],
    on_edit: Callable[[], None],
    on_delete: Callable[[], None],
) -> tuple[ttk.Button, ttk.Button, ttk.Button]:
    """Builds the "+ Add / Edit / Remove" button row used by record-list tabs."""
    btn_add = ttk.Button(parent, text="+ Add", command=on_add, width=12)
    btn_add.pack(side="left", padx=(0, 4))

    btn_edit = ttk.Button(parent, text="✏ Edit", command=on_edit, width=12)
    btn_edit.pack(side="left", padx=(0, 4))

    btn_delete = ttk.Button(
        parent, text="🗑 Remove", style="Danger.TButton", command=on_delete, width=12
    )
    btn_delete.pack(side="left")

    return btn_add, btn_edit, btn_delete
