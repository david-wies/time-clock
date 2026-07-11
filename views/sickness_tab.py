"""Sickness tab — balance summary, record list, and CRUD actions."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from tkinter import messagebox, ttk

from controllers.sickness_controller import SicknessController
from core.events import Event, EventBus
from core.hebrew_date import to_hebrew_label as _safe_hebrew
from core.timeutil import to_display_date
from domain.enums import WarningCode
from domain.types import SicknessRecord
from models.sickness_model import SicknessModel
from settings import SettingsManager
from theme.style import COLORS, ThemeMode, resolve_theme_mode
from views.record_tab_common import RecordTabMixin
from views.sick_record_dialog import SickRecordDialog
from views.tab_widgets import (
    build_action_bar,
    build_add_edit_remove_buttons,
    build_year_month_filter_bar,
)


class SicknessTab(RecordTabMixin, ttk.Frame):
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
        self._theme_mode: ThemeMode = resolve_theme_mode(self.settings.get("theme"))

        today = date.today()
        self._selected_year: int = today.year
        self._selected_month: int = 0  # 0 = All months
        self._unsubs: list[Callable] = []

        self._cbo_year: ttk.Combobox
        self._cbo_month: ttk.Combobox
        self._frm_balance: ttk.Frame
        self._lbl_balance: ttk.Label
        self._lbl_hours: ttk.Label
        self._btn_add: ttk.Button

        self._build_ui()
        self._refresh()

        self._unsubs.append(bus.subscribe(Event.SICKNESS_CHANGED, self._on_event))
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

        self._lbl_hours = ttk.Label(self._frm_balance, text="", foreground="gray")
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

        self._tree.column("date", width=110, minwidth=90, stretch=False, anchor="w")
        self._tree.heading("date", text="Date", anchor="center")

        self._tree.column(
            "hebrew_date", width=150, minwidth=120, stretch=False, anchor="w"
        )
        self._tree.heading("hebrew_date", text="Hebrew Date", anchor="center")

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

    def _build_action_bar(self) -> None:
        inner = build_action_bar(self)
        self._btn_add, self._btn_edit, self._btn_delete = build_add_edit_remove_buttons(
            inner, self._do_add, self._do_edit, self._do_delete
        )

    def _bind_shortcuts(self) -> None:
        self._bind_shortcut("<Control-Shift-S>", self._do_add)
        self._bind_shortcut("<Control-e>", self._do_edit)
        self._bind_shortcut("<Delete>", self._do_delete)
        self._bind_shortcut("<F5>", self._refresh)

    # ─────────────────────────── Balance Bar ────────────────────────────────

    def _refresh_balance(self, records: list[SicknessRecord]) -> None:
        year = self._selected_year
        summary = self.model.calculate_sickness_summary(year, records=records)
        used = summary.used_hours
        allowance = summary.allowance_hours
        remaining = summary.remaining_hours

        c = COLORS.get(self._theme_mode, COLORS[ThemeMode.LIGHT])
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

    def _make_row_values(
        self, rec: SicknessRecord | None, override_date: str = ""
    ) -> tuple:
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
                "",
                "end",
                iid=f"rec_{rec.id}",
                values=self._make_row_values(rec),
            )
            total_hours += rec.hours

        if records:
            self._tree.insert(
                "",
                "end",
                iid="__total__",
                values=self._make_row_values(None, f"Total: {total_hours:.1f}h"),
                tags=("total",),
            )
            c = COLORS.get(self._theme_mode, COLORS[ThemeMode.LIGHT])
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
        self._append_skip_notice(self._lbl_hours, self.model.last_skipped_count)
        self._update_button_states()

    def _on_event(self, **_kw) -> None:
        # Recompute theme mode in case the theme setting changed while this
        # tab was open — otherwise row colors stay stale until rebuilt.
        self._theme_mode = resolve_theme_mode(self.settings.get("theme"))
        self._refresh()

    # ─────────────────────────── Actions ────────────────────────────────────

    def _do_add(self) -> None:
        SickRecordDialog(
            self,
            controller=self.controller,
            model=self.model,
            record=None,
        )

    def _do_edit(self) -> None:
        rec_id = self._get_selected_record_id()
        if rec_id is None:
            return
        rec = self.model.get_record_by_id(rec_id)
        if rec is None:
            messagebox.showwarning(
                "Record Not Found",
                "This record could no longer be loaded — it may have been "
                "deleted or is corrupted. See the application log for details.",
                parent=self,
            )
            return
        dlg = SickRecordDialog(
            self,
            controller=self.controller,
            model=self.model,
            record=rec,
        )
        # The dialog is modal (wait_window in __init__), so by now it has
        # closed. If its save hit the RECORD_NOT_FOUND stale-record race,
        # no mutation event was published — refresh explicitly so the
        # phantom row disappears.
        if dlg.record_vanished:
            self._refresh()

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
            if WarningCode.RECORD_NOT_FOUND.value in result.errors:
                messagebox.showinfo(
                    "Record Already Removed",
                    "This record no longer exists — it may have already "
                    "been deleted elsewhere. The list will refresh.",
                    parent=self,
                )
                self._refresh()
                return
            messagebox.showerror("Remove Failed", "\n".join(result.errors), parent=self)
