"""Vacation tab — balance summary, record list, and CRUD actions."""

from __future__ import annotations

import tkinter as tk
from datetime import date
from tkinter import messagebox, ttk
from typing import Callable

from controllers.vacation_controller import VacationController
from core.events import Event, EventBus
from core.hebrew_date import to_hebrew_label as _safe_hebrew
from core.timeutil import to_display_date
from domain.enums import VacationType
from domain.types import VacationRecord
from models.vacation_model import VacationModel
from settings import SettingsManager
from theme.style import COLORS, ThemeMode, resolve_theme_mode
from views.carry_over_dialog import CarryOverDialog
from views.record_tab_common import RecordTabMixin
from views.tab_widgets import (
    build_action_bar,
    build_add_edit_remove_buttons,
    build_year_month_filter_bar,
)
from views.vacation_record_dialog import VacationRecordDialog

_VTYPE_LABELS: dict[VacationType, str] = {
    VacationType.ANNUAL_LEAVE: "Annual Leave",
    VacationType.PUBLIC_HOLIDAY: "Public Holiday",
    VacationType.SPECIAL_LEAVE: "Special Leave",
    VacationType.UNPAID_LEAVE: "Unpaid Leave",
    VacationType.CARRY_OVER: "Carry-Over",
}


def _fmt_h(hours: float) -> str:
    return f"{hours:.1f}h"


class VacationTab(RecordTabMixin, ttk.Frame):
    """Vacation tab: balance display, record list, add/edit/delete/carry-over."""

    def __init__(
        self,
        parent,
        controller: VacationController,
        model: VacationModel,
        settings: SettingsManager,
        bus: EventBus,
        root,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self.model = model
        self.settings = settings
        self.bus = bus
        self.root = root
        self._theme_mode: ThemeMode = resolve_theme_mode(self.settings.get("theme"))

        today = date.today()
        self._selected_year: int = today.year
        self._selected_month: int = 0  # 0 = All months
        self._unsubs: list[Callable] = []

        self._cbo_year: ttk.Combobox
        self._cbo_month: ttk.Combobox
        self._frm_balance: ttk.Frame
        self._lbl_balance: ttk.Label
        self._lbl_breakdown: ttk.Label
        self._btn_add: ttk.Button
        self._btn_carry_over: ttk.Button

        self._build_ui()
        self._refresh()

        self._unsubs.append(bus.subscribe(Event.VACATION_CHANGED, self._on_event))
        self._unsubs.append(bus.subscribe(Event.SETTINGS_CHANGED, self._on_event))

        self.bind("<Destroy>", self._on_destroy)
        self.pack(fill="both", expand=True)

    # ─────────────────────────── UI Construction ────────────────────────────

    def _build_ui(self) -> None:
        self._build_filter_bar()
        self._build_balance_bar()
        self._build_treeview()
        self._build_action_bar()
        self._bind_shortcuts()

    def _build_filter_bar(self) -> None:
        self._var_year, self._var_month, self._cbo_year, self._cbo_month = (
            build_year_month_filter_bar(
                self, self._selected_year, self._on_period_changed
            )
        )

    def _build_balance_bar(self) -> None:
        self._frm_balance = ttk.Frame(self, style="Card.TFrame")
        self._frm_balance.pack(fill="x", padx=4, pady=(4, 0))

        self._lbl_balance = ttk.Label(
            self._frm_balance, text="", style="DayHeader.TLabel"
        )
        self._lbl_balance.pack(side="left", padx=10, pady=5)

        ttk.Separator(self._frm_balance, orient="vertical").pack(
            side="left", fill="y", pady=5
        )

        self._lbl_breakdown = ttk.Label(self._frm_balance, text="", foreground="gray")
        self._lbl_breakdown.pack(side="left", padx=10, pady=5)

        self._build_legend()

    def _build_legend(self) -> None:
        c = COLORS.get(self._theme_mode, COLORS[ThemeMode.LIGHT])
        legend_frame = ttk.Frame(self)
        legend_frame.pack(fill="x", padx=10, pady=(2, 0))

        items = [
            ("● Used", c["fg.default"], "normal"),
            ("● Planned", c["accent"], "italic"),
            ("● Employer (Holiday)", c["success"], "normal"),
            ("● Unpaid", c["fg.muted"], "normal"),
        ]
        for text, color, style_modifier in items:
            ttk.Label(
                legend_frame,
                text=text,
                foreground=color,
                font=("Helvetica", 8, style_modifier),
            ).pack(side="left", padx=(0, 12))

    def _build_treeview(self) -> None:
        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True, padx=4, pady=4)

        cols = ["date", "hebrew_date", "type", "hours", "note"]

        self._tree = ttk.Treeview(
            frame,
            columns=cols,
            show="headings",
            selectmode="browse",
        )

        self._tree.column("date", width=110, minwidth=90, stretch=False, anchor="w")
        self._tree.heading("date", text="Date", anchor="center")

        self._tree.column(
            "hebrew_date", width=150, minwidth=120, stretch=False, anchor="w"
        )
        self._tree.heading("hebrew_date", text="Hebrew Date", anchor="center")

        self._tree.column("type", width=140, minwidth=100, stretch=False, anchor="w")
        self._tree.heading("type", text="Type", anchor="center")

        self._tree.column("hours", width=70, minwidth=50, stretch=False, anchor="e")
        self._tree.heading("hours", text="Hours", anchor="center")

        self._tree.column("note", width=200, minwidth=80, stretch=True, anchor="w")
        self._tree.heading("note", text="Note", anchor="center")

        vsb = ttk.Scrollbar(frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._tree.pack(side="left", fill="both", expand=True)

        self._tree.bind("<Double-1>", self._on_double_click)
        self._tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        c = COLORS.get(self._theme_mode, COLORS[ThemeMode.LIGHT])
        self._tree.tag_configure("employer", foreground=c["success"])
        self._tree.tag_configure(
            "planned",
            foreground=c["accent"],
            font=("Helvetica", 9, "italic"),
        )
        self._tree.tag_configure("carry_over", foreground=c["accent"])
        self._tree.tag_configure("unpaid", foreground=c["fg.muted"])

    def _build_action_bar(self) -> None:
        inner = build_action_bar(self)
        self._btn_add, self._btn_edit, self._btn_delete = build_add_edit_remove_buttons(
            inner, self._do_add, self._do_edit, self._do_delete
        )

        ttk.Separator(inner, orient="vertical").pack(
            side="left", fill="y", padx=10, pady=2
        )

        self._btn_carry_over = ttk.Button(
            inner, text="+ Add Carry-Over", command=self._do_carry_over, width=18
        )
        self._btn_carry_over.pack(side="left")

    def _bind_shortcuts(self) -> None:
        def _guard(fn: Callable) -> Callable:
            def _handler(_e=None) -> None:
                try:
                    # bind_all is process-wide: all 4 tab frames coexist in the
                    # Notebook, so without the winfo_ismapped() check a
                    # shortcut fires on every hidden tab too, not just the
                    # one currently selected/visible.
                    if self.winfo_exists() and self.winfo_ismapped():
                        fn()
                except tk.TclError:
                    pass

            return _handler

        self.root.bind_all("<Control-Shift-N>", _guard(self._do_add), add=True)
        self.root.bind_all("<Control-e>", _guard(self._do_edit), add=True)
        self.root.bind_all("<Delete>", _guard(self._do_delete), add=True)
        self.root.bind_all("<F5>", _guard(self._refresh), add=True)

    # ─────────────────────────── Balance Bar ────────────────────────────────

    def _refresh_balance(self, records: list[VacationRecord]) -> None:
        year = self._selected_year
        summary = self.model.calculate_vacation_summary(year, records=records)

        used = summary.used
        total_pool = summary.total_pool
        remaining = summary.remaining
        carry_over = summary.carry_over
        allowance = summary.allowance

        c = COLORS.get(self._theme_mode, COLORS[ThemeMode.LIGHT])
        if remaining < 0:
            bal_color = c["warning"]
        elif remaining == 0:
            bal_color = c["fg.muted"]
        else:
            bal_color = c["success"]

        balance_text = (
            f"Vacation {year}: {_fmt_h(used)} / {_fmt_h(total_pool)} available"
            f"  |  Remaining: {_fmt_h(remaining)}"
        )
        self._lbl_balance.config(
            text=balance_text,
            foreground=bal_color,
        )

        parts = [f"allowance: {_fmt_h(allowance)}"]
        if carry_over > 0:
            parts.append(f"carry-over: +{_fmt_h(carry_over)}")
        self._lbl_breakdown.config(text="  ".join(parts))

    # ─────────────────────────── Treeview Population ────────────────────────

    def _clear_tree(self) -> None:
        children = self._tree.get_children()
        if children:
            self._tree.delete(*children)

    def _refresh_tree(self, year_records: list[VacationRecord]) -> None:
        self._clear_tree()
        month = self._selected_month if self._selected_month > 0 else None
        if month is None:
            records = year_records
        else:
            # Filter the already-fetched full-year list in Python instead
            # of issuing a second SQL query for the same year's data.
            records = [r for r in year_records if r.date.month == month]

        total_hours = 0.0
        for rec in records:
            self._insert_record_row(rec)
            total_hours += rec.hours

        if records:
            self._tree.insert(
                "",
                "end",
                iid="__total__",
                values=self._make_row_values(None, f"Total: {_fmt_h(total_hours)}"),
                tags=("total",),
            )
            c = COLORS.get(self._theme_mode, COLORS[ThemeMode.LIGHT])
            self._tree.tag_configure(
                "total", foreground=c["fg.muted"], font=("Helvetica", 9, "bold")
            )

    def _make_row_values(
        self, rec: VacationRecord | None, override_date: str = ""
    ) -> tuple:
        if rec is None:
            return (override_date, "", "", "", "")

        disp = to_display_date(rec.date)
        type_label = _VTYPE_LABELS.get(rec.vtype, str(rec.vtype))
        hours_str = _fmt_h(rec.hours)
        note = rec.note or ""
        return (disp, _safe_hebrew(rec.date), type_label, hours_str, note)

    def _insert_record_row(self, rec: VacationRecord) -> None:
        if rec.vtype == VacationType.PUBLIC_HOLIDAY:
            tag = "employer"
        elif rec.vtype == VacationType.CARRY_OVER:
            tag = "carry_over"
        elif rec.vtype == VacationType.UNPAID_LEAVE:
            tag = "unpaid"
        elif rec.date > date.today():
            tag = "planned"
        else:
            tag = ""

        self._tree.insert(
            "",
            "end",
            iid=f"rec_{rec.id}",
            values=self._make_row_values(rec),
            tags=(tag,) if tag else (),
        )

    # ─────────────────────────── Refresh ────────────────────────────────────

    def _refresh(self, **_kw) -> None:
        # Fetch the full year's records once per refresh cycle and share
        # them between the balance summary and the tree, instead of each
        # independently querying get_records_for_year() for the same data.
        year_records = self.model.get_records_for_year(self._selected_year)
        self._refresh_balance(year_records)
        self._refresh_tree(year_records)
        self._append_skip_notice(self._lbl_breakdown, self.model.last_skipped_count)
        self._update_button_states()

    def _on_event(self, **_kw) -> None:
        self._refresh()

    # ─────────────────────────── Button State ───────────────────────────────

    def _get_selected_record(self) -> VacationRecord | None:
        rec_id = self._get_selected_record_id()
        return self.model.get_record_by_id(rec_id) if rec_id is not None else None

    # ─────────────────────────── Actions ────────────────────────────────────

    def _do_add(self) -> None:
        VacationRecordDialog(
            self,
            controller=self.controller,
            model=self.model,
            record=None,
        )

    def _do_edit(self) -> None:
        rec = self._get_selected_record()
        if rec is None:
            return
        VacationRecordDialog(
            self,
            controller=self.controller,
            model=self.model,
            record=rec,
        )

    def _do_delete(self) -> None:
        rec_id = self._get_selected_record_id()
        if rec_id is None:
            return
        if not messagebox.askyesno(
            "Confirm Remove",
            "Permanently remove this vacation record?",
            icon="warning",
            parent=self,
        ):
            return
        result = self.controller.delete_record(rec_id)
        if not result.ok:
            messagebox.showerror("Remove Failed", "\n".join(result.errors), parent=self)

    def _do_carry_over(self) -> None:
        CarryOverDialog(
            self,
            controller=self.controller,
            model=self.model,
            to_year=self._selected_year,
        )
