"""Sickness tab — balance summary, record list, and CRUD actions."""

from __future__ import annotations

from datetime import date
from typing import Optional, Callable

import tkinter as tk
from tkinter import ttk, messagebox

from controllers.sickness_controller import SicknessController
from models.sickness_model import SicknessModel
from settings import SettingsManager
from core.events import EventBus, Event
from core.timeutil import to_display_date
from domain.types import SicknessRecord
from theme.style import COLORS, resolve_theme_mode

from core.hebrew_date import to_hebrew_label as _safe_hebrew
from views.sick_record_dialog import SickRecordDialog


_MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


class SicknessTab(ttk.Frame):
    """Sickness tab: balance display, record list, add/edit/delete."""

    def __init__(
        self,
        parent,
        controller: SicknessController,
        model: SicknessModel,
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
        self._selected_month: int = 0  # 0 = All months
        self._unsubs: list[Callable] = []
        self._build_ui()
        self._refresh()

        self._unsubs.append(bus.subscribe(
            Event.SICKNESS_CHANGED, self._on_event))
        self._unsubs.append(bus.subscribe(
            Event.SETTINGS_CHANGED, self._on_event))

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
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=4, pady=(4, 0))

        ttk.Label(bar, text="Year:").pack(side="left")
        cur_year = date.today().year
        self._var_year = tk.StringVar(value=str(self._selected_year))
        self._cbo_year = ttk.Combobox(
            bar, textvariable=self._var_year, width=6,
            values=[str(y) for y in range(cur_year - 10, cur_year + 3)],
            state="readonly",
        )
        self._cbo_year.pack(side="left", padx=(2, 10))
        self._cbo_year.bind("<<ComboboxSelected>>", self._on_period_changed)

        ttk.Label(bar, text="Month:").pack(side="left")
        self._var_month = tk.StringVar(value="All")
        self._cbo_month = ttk.Combobox(
            bar, textvariable=self._var_month, width=11,
            values=["All"] + _MONTH_NAMES[1:],
            state="readonly",
        )
        self._cbo_month.pack(side="left", padx=(2, 0))
        self._cbo_month.bind("<<ComboboxSelected>>", self._on_period_changed)

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

        self._lbl_hours = ttk.Label(
            self._frm_balance, text="", foreground="gray")
        self._lbl_hours.pack(side="left", padx=10, pady=5)

    def _build_treeview(self) -> None:
        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True, padx=4, pady=4)

        cols = ["date", "hebrew_date", "hours", "note"]

        self._tree = ttk.Treeview(
            frame,
            columns=cols,
            show="headings",
            selectmode="browse",
        )

        self._tree.column("date", width=110, minwidth=90,
                          stretch=False, anchor="w")
        self._tree.heading("date", text="Date", anchor="center")

        self._tree.column("hebrew_date", width=150,
                          minwidth=120, stretch=False, anchor="w")
        self._tree.heading("hebrew_date", text="Hebrew Date", anchor="center")

        self._tree.column("hours", width=70, minwidth=50,
                          stretch=False, anchor="e")
        self._tree.heading("hours", text="Hours", anchor="center")

        self._tree.column("note", width=200, minwidth=80,
                          stretch=True, anchor="w")
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

        self._btn_add = ttk.Button(
            inner, text="+ Add", command=self._do_add, width=12
        )
        self._btn_add.pack(side="left", padx=(0, 4))

        self._btn_edit = ttk.Button(
            inner, text="✏ Edit", command=self._do_edit, width=12
        )
        self._btn_edit.pack(side="left", padx=(0, 4))

        self._btn_delete = ttk.Button(
            inner, text="🗑 Remove", style="Danger.TButton",
            command=self._do_delete, width=12,
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

        self.root.bind_all("<Control-Shift-S>", _guard(self._do_add), add=True)
        self.root.bind_all("<Control-e>",       _guard(self._do_edit), add=True)
        self.root.bind_all("<Delete>",          _guard(self._do_delete), add=True)
        self.root.bind_all("<F5>",              _guard(self._refresh), add=True)

    # ─────────────────────────── Period Filter ──────────────────────────────

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

    # ─────────────────────────── Balance Bar ────────────────────────────────

    def _refresh_balance(self, records: list[SicknessRecord]) -> None:
        year = self._selected_year
        summary = self.model.calculate_sickness_summary(year, records=records)
        used = summary.used_hours
        allowance = summary.allowance_hours
        remaining = summary.remaining_hours

        c = COLORS.get(self._theme_mode, COLORS["light"])
        if remaining < 0:
            bal_color = c["warning"]
        elif remaining == 0:
            bal_color = c["fg.muted"]
        else:
            bal_color = c["success"]

        self._lbl_balance.config(
            text=(
                f"Sick hours {year}: {used:.1f}h / {allowance:.1f}h used"
                f"  |  Remaining: {remaining:.1f}h"
            ),
            foreground=bal_color,
        )
        self._lbl_hours.config(text="")

    # ─────────────────────────── Treeview Population ────────────────────────

    def _clear_tree(self) -> None:
        children = self._tree.get_children()
        if children:
            self._tree.delete(*children)

    def _make_row_values(self, rec: Optional[SicknessRecord], override_date: str = "") -> tuple:
        if rec is None:
            return (override_date, "", "", "")

        disp = to_display_date(rec.date)
        hours_str = f"{rec.hours:.1f}h"
        note = rec.note or ""
        return (disp, _safe_hebrew(rec.date), hours_str, note)

    def _refresh_tree(self, year_records: list[SicknessRecord]) -> None:
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
            self._tree.insert(
                "", "end",
                iid=f"rec_{rec.id}",
                values=self._make_row_values(rec),
            )
            total_hours += rec.hours

        if records:
            self._tree.insert(
                "", "end",
                iid="__total__",
                values=self._make_row_values(None, f"Total: {total_hours:.1f}h"),
                tags=("total",),
            )
            c = COLORS.get(self._theme_mode, COLORS["light"])
            self._tree.tag_configure(
                "total", foreground=c["fg.muted"], font=("Helvetica", 9, "bold")
            )

    # ─────────────────────────── Refresh ────────────────────────────────────

    def _refresh(self, **_kw) -> None:
        # Fetch the full year's records once per refresh cycle and share
        # them between the balance summary and the tree, instead of each
        # independently querying get_records_for_year() for the same data.
        year_records = self.model.get_records_for_year(self._selected_year)
        self._refresh_balance(year_records)
        self._refresh_tree(year_records)
        self._update_button_states()

    def _on_event(self, **_kw) -> None:
        self._refresh()

    # ─────────────────────────── Button State ───────────────────────────────

    def _update_button_states(self) -> None:
        state = "normal" if self._get_selected_record_id() is not None else "disabled"
        self._btn_edit.config(state=state)
        self._btn_delete.config(state=state)

    def _get_selected_record_id(self) -> Optional[int]:
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

    def _get_selected_record(self) -> Optional[SicknessRecord]:
        rec_id = self._get_selected_record_id()
        return self.model.get_record_by_id(rec_id) if rec_id is not None else None

    # ─────────────────────────── Tree Callbacks ─────────────────────────────

    def _on_double_click(self, event: tk.Event) -> None:
        iid = self._tree.identify_row(event.y)
        if iid and iid.startswith("rec_"):
            self._tree.selection_set(iid)
            self._do_edit()

    def _on_tree_select(self, _event=None) -> None:
        state = "normal" if self._get_selected_record_id() is not None else "disabled"
        self._btn_edit.config(state=state)
        self._btn_delete.config(state=state)

    # ─────────────────────────── Actions ────────────────────────────────────

    def _do_add(self) -> None:
        SickRecordDialog(
            self, controller=self.controller, model=self.model, record=None,
        )

    def _do_edit(self) -> None:
        rec = self._get_selected_record()
        if rec is None:
            return
        SickRecordDialog(
            self, controller=self.controller, model=self.model, record=rec,
        )

    def _do_delete(self) -> None:
        rec_id = self._get_selected_record_id()
        if rec_id is None:
            return
        if not messagebox.askyesno(
            "Confirm Remove",
            "Permanently remove this sick record?",
            icon="warning",
            parent=self,
        ):
            return
        result = self.controller.delete_record(rec_id)
        if not result.ok:
            messagebox.showerror("Remove Failed", "\n".join(
                result.errors), parent=self)

    # ─────────────────────────── Lifecycle ──────────────────────────────────

    def _on_destroy(self, _event=None) -> None:
        for unsub in self._unsubs:
            try:
                unsub()
            except Exception:
                pass
        self._unsubs.clear()
