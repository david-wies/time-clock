"""Miliuim (Army Reserve) tab — period list and CRUD actions."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from tkinter import messagebox, ttk

from controllers.miliuim_controller import MiliuimController
from core.events import Event, EventBus
from core.hebrew_date import to_hebrew_label as _safe_hebrew
from core.timeutil import date_to_iso, period_bounds, to_display_date
from domain.enums import WarningCode
from domain.types import MiliuimRecord
from models.miliuim_model import MiliuimModel
from settings import SettingsManager
from theme.style import COLORS, ThemeMode, resolve_theme_mode
from views.miliuim_record_dialog import MiliuimRecordDialog
from views.record_tab_common import RecordTabMixin
from views.tab_widgets import (
    build_action_bar,
    build_add_edit_remove_buttons,
    build_year_month_filter_bar,
)


class MiliuimTab(RecordTabMixin, ttk.Frame):
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
        self._theme_mode: ThemeMode = resolve_theme_mode(self.settings.get("theme"))

        today = date.today()
        self._selected_year: int = today.year
        self._selected_month: int = 0
        self._unsubs: list[Callable] = []

        self._cbo_year: ttk.Combobox
        self._cbo_month: ttk.Combobox
        self._frm_summary: ttk.Frame
        self._lbl_summary: ttk.Label
        self._btn_add: ttk.Button

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
        self._var_year, self._var_month, self._cbo_year, self._cbo_month = (
            build_year_month_filter_bar(
                self, self._selected_year, self._on_period_changed
            )
        )

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
        inner = build_action_bar(self)
        self._btn_add, self._btn_edit, self._btn_delete = build_add_edit_remove_buttons(
            inner, self._do_add, self._do_edit, self._do_delete
        )

    def _bind_shortcuts(self) -> None:
        self._bind_shortcut("<Control-Shift-M>", self._do_add)
        self._bind_shortcut("<F5>", self._refresh)

    def _refresh_summary(self, records: list[MiliuimRecord]) -> None:
        year = self._selected_year
        summary = self.model.calculate_summary(year, records=records)
        c = COLORS.get(self._theme_mode, COLORS[ThemeMode.LIGHT])
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
            c = COLORS.get(self._theme_mode, COLORS[ThemeMode.LIGHT])
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
        self._append_skip_notice(self._lbl_summary, self.model.last_skipped_count)
        self._update_button_states()

    def _on_event(self, **_kw) -> None:
        self._refresh()

    def _on_settings_changed(self, **_kw) -> None:
        self._theme_mode = resolve_theme_mode(self.settings.get("theme"))
        self._refresh()

    def _do_add(self) -> None:
        MiliuimRecordDialog(
            self, controller=self.controller, model=self.model, record=None
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
        dlg = MiliuimRecordDialog(
            self, controller=self.controller, model=self.model, record=rec
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
            "Permanently remove this Miliuim period?",
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
