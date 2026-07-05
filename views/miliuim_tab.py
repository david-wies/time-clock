"""Miliuim (Army Reserve) tab — period list and CRUD actions."""

from __future__ import annotations

import tkinter as tk
from datetime import date
from tkinter import messagebox, ttk
from typing import Callable

from controllers.miliuim_controller import MiliuimController
from core.events import Event, EventBus
from core.hebrew_date import to_hebrew_label as _safe_hebrew
from core.timeutil import date_to_iso, period_bounds, to_display_date
from domain.types import MiliuimRecord
from models.miliuim_model import MiliuimModel
from settings import SettingsManager
from theme.style import COLORS, resolve_theme_mode
from views.miliuim_record_dialog import MiliuimRecordDialog

_MONTH_NAMES = [
    "",
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


class MiliuimTab(ttk.Frame):
    """Miliuim tab: summary display, period list, add/edit/delete."""

    def __init__(
        self,
        parent,
        controller: MiliuimController,
        model: MiliuimModel,
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
        self._theme_mode: str = resolve_theme_mode(self.settings.get("theme"))

        today = date.today()
        self._selected_year: int = today.year
        self._selected_month: int = 0
        self._unsubs: list[Callable] = []
        self._build_ui()
        self._refresh()

        self._unsubs.append(bus.subscribe(Event.MILIUIM_CHANGED, self._on_event))
        self._unsubs.append(
            bus.subscribe(Event.SETTINGS_CHANGED, self._on_settings_changed)
        )

        self.bind("<Destroy>", self._on_destroy)
        self.pack(fill="both", expand=True)

    def _build_ui(self) -> None:
        self._build_filter_bar()
        self._build_summary_bar()
        self._build_treeview()
        self._build_action_bar()
        self._bind_shortcuts()

    def _build_filter_bar(self) -> None:
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=4, pady=(4, 0))

        ttk.Label(bar, text="Year:").pack(side="left")
        cur_year = date.today().year
        self._var_year = tk.StringVar(value=str(self._selected_year))
        self._cbo_year = ttk.Combobox(
            bar,
            textvariable=self._var_year,
            width=6,
            values=[str(y) for y in range(cur_year - 10, cur_year + 3)],
            state="readonly",
        )
        self._cbo_year.pack(side="left", padx=(2, 10))
        self._cbo_year.bind("<<ComboboxSelected>>", self._on_period_changed)

        ttk.Label(bar, text="Month:").pack(side="left")
        self._var_month = tk.StringVar(value="All")
        self._cbo_month = ttk.Combobox(
            bar,
            textvariable=self._var_month,
            width=11,
            values=["All"] + _MONTH_NAMES[1:],
            state="readonly",
        )
        self._cbo_month.pack(side="left", padx=(2, 0))
        self._cbo_month.bind("<<ComboboxSelected>>", self._on_period_changed)

    def _build_summary_bar(self) -> None:
        self._frm_summary = ttk.Frame(self, style="Card.TFrame")
        self._frm_summary.pack(fill="x", padx=4, pady=(4, 0))

        self._lbl_summary = ttk.Label(
            self._frm_summary, text="", style="DayHeader.TLabel"
        )
        self._lbl_summary.pack(side="left", padx=10, pady=5)

    def _build_treeview(self) -> None:
        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True, padx=4, pady=4)

        cols = ["start_date", "end_date", "hebrew_date", "days", "note"]

        self._tree = ttk.Treeview(
            frame,
            columns=cols,
            show="headings",
            selectmode="browse",
        )
        self._tree.column(
            "start_date", width=110, minwidth=90, stretch=False, anchor="w"
        )
        self._tree.heading("start_date", text="Start Date", anchor="center")

        self._tree.column("end_date", width=110, minwidth=90, stretch=False, anchor="w")
        self._tree.heading("end_date", text="End Date", anchor="center")

        self._tree.column(
            "hebrew_date", width=150, minwidth=120, stretch=False, anchor="w"
        )
        self._tree.heading("hebrew_date", text="Hebrew Date (Start)", anchor="center")

        self._tree.column("days", width=60, minwidth=50, stretch=False, anchor="e")
        self._tree.heading("days", text="Days", anchor="center")

        self._tree.column("note", width=200, minwidth=80, stretch=True, anchor="w")
        self._tree.heading("note", text="Note", anchor="center")

        vsb = ttk.Scrollbar(frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._tree.pack(side="left", fill="both", expand=True)

        self._tree.bind("<Double-1>", self._on_double_click)
        self._tree.bind("<<TreeviewSelect>>", self._on_tree_select)

    def _build_action_bar(self) -> None:
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=4, pady=(0, 6))

        ttk.Separator(bar, orient="horizontal").pack(fill="x", pady=(0, 6))

        inner = ttk.Frame(bar)
        inner.pack(fill="x")

        self._btn_add = ttk.Button(inner, text="+ Add", command=self._do_add, width=12)
        self._btn_add.pack(side="left", padx=(0, 4))

        self._btn_edit = ttk.Button(
            inner, text="✏ Edit", command=self._do_edit, width=12
        )
        self._btn_edit.pack(side="left", padx=(0, 4))

        self._btn_delete = ttk.Button(
            inner,
            text="🗑 Remove",
            style="Danger.TButton",
            command=self._do_delete,
            width=12,
        )
        self._btn_delete.pack(side="left")

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

        self.root.bind_all("<Control-Shift-M>", _guard(self._do_add), add=True)
        self.root.bind_all("<F5>", _guard(self._refresh), add=True)

    def _on_period_changed(self, _event=None) -> None:
        try:
            self._selected_year = int(self._var_year.get())
        except ValueError:
            pass
        month_name = self._var_month.get()
        if month_name == "All":
            self._selected_month = 0
        elif month_name in _MONTH_NAMES:
            idx = _MONTH_NAMES.index(month_name)
            self._selected_month = idx if idx > 0 else 0
        self._refresh()

    def _refresh_summary(self, records: list[MiliuimRecord]) -> None:
        year = self._selected_year
        summary = self.model.calculate_summary(year, records=records)
        c = COLORS.get(self._theme_mode, COLORS["light"])
        text = (
            f"Miliuim {year}: {summary.period_count} period(s)"
            f"  |  {summary.total_days} day(s) total"
        )
        self._lbl_summary.config(text=text, foreground=c["fg.muted"])

    def _clear_tree(self) -> None:
        children = self._tree.get_children()
        if children:
            self._tree.delete(*children)

    def _make_row_values(self, rec: MiliuimRecord, month: int | None) -> tuple:
        days = self.model.clip_days(rec, self._selected_year, month)
        return (
            to_display_date(rec.start_date),
            to_display_date(rec.end_date),
            _safe_hebrew(rec.start_date),
            str(days),
            rec.note or "",
        )

    def _refresh_tree(self, year_records: list[MiliuimRecord]) -> None:
        self._clear_tree()
        month = self._selected_month if self._selected_month > 0 else None
        if month is None:
            records = year_records
        else:
            # Filter the already-fetched full-year list in Python instead of
            # issuing a second SQL query for the same year's data. Mirrors
            # the overlap test get_records_for_year() runs in SQL: a period
            # is included if it overlaps the selected month at all.
            period_start, period_end = period_bounds(self._selected_year, month)
            records = [
                r
                for r in year_records
                if date_to_iso(r.start_date) <= period_end
                and date_to_iso(r.end_date) >= period_start
            ]

        total_days = 0
        for rec in records:
            self._tree.insert(
                "", "end", iid=f"rec_{rec.id}", values=self._make_row_values(rec, month)
            )
            total_days += self.model.clip_days(rec, self._selected_year, month)

        if records:
            self._tree.insert(
                "",
                "end",
                iid="__total__",
                values=("", "", "", str(total_days), f"Total: {total_days} days"),
                tags=("total",),
            )
            c = COLORS.get(self._theme_mode, COLORS["light"])
            self._tree.tag_configure(
                "total", foreground=c["fg.muted"], font=("Helvetica", 9, "bold")
            )

    def _refresh(self, **_kw) -> None:
        # Fetch the full year's records once per refresh cycle and share
        # them between the summary and the tree, instead of each
        # independently querying get_records_for_year() for the same data.
        year_records = self.model.get_records_for_year(self._selected_year)
        self._refresh_summary(year_records)
        self._refresh_tree(year_records)
        self._update_button_states()

    def _on_event(self, **_kw) -> None:
        self._refresh()

    def _on_settings_changed(self, **_kw) -> None:
        self._theme_mode = resolve_theme_mode(self.settings.get("theme"))
        self._refresh()

    def _update_button_states(self) -> None:
        state = "normal" if self._get_selected_record_id() is not None else "disabled"
        self._btn_edit.config(state=state)
        self._btn_delete.config(state=state)

    def _get_selected_record_id(self) -> int | None:
        sel = self._tree.selection()
        if not sel:
            return None
        iid = sel[0]
        if iid.startswith("rec_"):
            try:
                return int(iid[4:])
            except ValueError:
                return None
        return None

    def _get_selected_record(self) -> MiliuimRecord | None:
        rec_id = self._get_selected_record_id()
        return self.model.get_record_by_id(rec_id) if rec_id is not None else None

    def _on_double_click(self, event: tk.Event) -> None:
        iid = self._tree.identify_row(event.y)
        if iid and iid.startswith("rec_"):
            self._tree.selection_set(iid)
            self._do_edit()

    def _on_tree_select(self, _event=None) -> None:
        state = "normal" if self._get_selected_record_id() is not None else "disabled"
        self._btn_edit.config(state=state)
        self._btn_delete.config(state=state)

    def _do_add(self) -> None:
        MiliuimRecordDialog(
            self, controller=self.controller, model=self.model, record=None
        )

    def _do_edit(self) -> None:
        rec = self._get_selected_record()
        if rec is None:
            return
        MiliuimRecordDialog(
            self, controller=self.controller, model=self.model, record=rec
        )

    def _do_delete(self) -> None:
        rec_id = self._get_selected_record_id()
        if rec_id is None:
            return
        if not messagebox.askyesno(
            "Confirm Remove",
            "Permanently remove this Miliuim period?",
            icon="warning",
            parent=self,
        ):
            return
        result = self.controller.delete_record(rec_id)
        if not result.ok:
            messagebox.showerror("Remove Failed", "\n".join(result.errors), parent=self)

    def _on_destroy(self, _event=None) -> None:
        for unsub in self._unsubs:
            try:
                unsub()
            except Exception:
                pass
        self._unsubs.clear()
