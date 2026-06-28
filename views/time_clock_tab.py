"""Time Clock tab — grouped record list, clock-in/out, and inline edit/delete."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Optional, Callable

import tkinter as tk
from tkinter import ttk, messagebox

from controllers.time_clock_controller import TimeClockController
from models.time_clock_model import TimeClockModel
from settings import SettingsManager
from core.events import EventBus, Event
from core.timeutil import to_display_date, time_to_str
from core.balance import (
    get_daily_target,
    get_record_duration,
    calculate_period_balance,
    get_month_range,
)
from domain.types import TimeRecord
from domain.enums import WorkType
from theme.style import COLORS

try:
    from core.hebrew_date import to_hebrew_label as _hebrew_impl

    def _safe_hebrew(d: date) -> Optional[str]:
        try:
            return _hebrew_impl(d)
        except Exception:
            return None

except ImportError:
    def _safe_hebrew(d: date) -> Optional[str]:  # type: ignore[misc]
        return None


_MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

_DAY_NAMES = [
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
]

_WORK_TYPE_LABELS: dict[WorkType, str] = {
    WorkType.IN_SITE: "In-Site",
    WorkType.ROAD: "Road",
    WorkType.REMOTE: "Remote",
}


def _fmt_h(hours: float) -> str:
    return f"{hours:.1f}h"


def _now_time() -> time:
    return datetime.now().time().replace(second=0, microsecond=0)


def _build_exc_dict(raw: list[dict]) -> dict[date, float]:
    result: dict[date, float] = {}
    for exc in raw:
        try:
            d = date.fromisoformat(exc["date"])
            result[d] = float(exc["hours"])
        except (KeyError, ValueError):
            pass
    return result


class TimeClockTab(ttk.Frame):
    """Time Clock tab: view, clock-in/out, and manage time records."""

    def __init__(
        self,
        parent,
        controller: TimeClockController,
        model: TimeClockModel,
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

        today = date.today()
        self._view_mode: str = self.settings.get("view_mode") or "month"
        self._selected_year: int = today.year
        self._selected_month: int = today.month
        self._selected_week_start: date = today - \
            timedelta(days=today.weekday())
        self._after_id: Optional[str] = None
        self._unsubs: list[Callable] = []

        self._build_ui()
        self._apply_tag_styles()

        self._refresh()
        if self.model.get_open_records():
            self._start_auto_refresh()

        self._unsubs.append(bus.subscribe(
            Event.TIME_RECORDS_CHANGED, self._on_event))
        self._unsubs.append(bus.subscribe(
            Event.SETTINGS_CHANGED, self._on_event))

        self.bind("<Destroy>", self._on_destroy)
        self.pack(fill="both", expand=True)

    # ─────────────────────────── UI Construction ────────────────────────────

    def _build_ui(self) -> None:
        self._build_header_bar()
        self._build_toolbar()
        self._build_treeview()
        self._build_action_bar()
        self._bind_shortcuts()

    def _build_header_bar(self) -> None:
        bar = ttk.Frame(self, style="Card.TFrame")
        bar.pack(fill="x", padx=4, pady=(4, 0))

        self._lbl_today = ttk.Label(bar, text="", style="DayHeader.TLabel")
        self._lbl_today.pack(side="left", padx=(10, 6), pady=5)

        ttk.Separator(bar, orient="vertical").pack(
            side="left", fill="y", pady=5)

        self._lbl_target = ttk.Label(bar, text="")
        self._lbl_target.pack(side="left", padx=(8, 6), pady=5)

        ttk.Separator(bar, orient="vertical").pack(
            side="left", fill="y", pady=5)

        self._lbl_remaining = ttk.Label(bar, text="")
        self._lbl_remaining.pack(side="left", padx=(8, 10), pady=5)

    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=4, pady=(4, 0))

        # View-mode toggle
        self._btn_week = ttk.Button(
            bar, text="Week", width=7, command=lambda: self._set_view_mode("week")
        )
        self._btn_week.pack(side="left", padx=(0, 2))

        self._btn_month = ttk.Button(
            bar, text="Month", width=7, command=lambda: self._set_view_mode("month")
        )
        self._btn_month.pack(side="left", padx=(0, 8))

        ttk.Separator(bar, orient="vertical").pack(
            side="left", fill="y", padx=(0, 8), pady=3)

        # Week-mode controls (shown/hidden by _refresh_toolbar)
        self._frm_week = ttk.Frame(bar)
        ttk.Button(self._frm_week, text="◀", width=3, command=self._prev_week).pack(
            side="left", padx=(0, 4)
        )
        self._lbl_week_range = ttk.Label(self._frm_week, text="", width=24)
        self._lbl_week_range.pack(side="left", padx=(0, 4))
        ttk.Button(self._frm_week, text="▶", width=3,
                   command=self._next_week).pack(side="left")

        # Month-mode controls (shown/hidden by _refresh_toolbar)
        self._frm_month = ttk.Frame(bar)
        ttk.Label(self._frm_month, text="Year:").pack(side="left")
        self._var_year = tk.StringVar(value=str(self._selected_year))
        cur_year = date.today().year
        self._cbo_year = ttk.Combobox(
            self._frm_month, textvariable=self._var_year, width=6,
            values=[str(y) for y in range(cur_year - 10, cur_year + 3)],
            state="readonly",
        )
        self._cbo_year.pack(side="left", padx=(2, 10))
        self._cbo_year.bind("<<ComboboxSelected>>", self._on_period_changed)

        ttk.Label(self._frm_month, text="Month:").pack(side="left")
        self._var_month = tk.StringVar(
            value=_MONTH_NAMES[self._selected_month])
        self._cbo_month = ttk.Combobox(
            self._frm_month, textvariable=self._var_month, width=11,
            values=_MONTH_NAMES[1:],
            state="readonly",
        )
        self._cbo_month.pack(side="left", padx=(2, 0))
        self._cbo_month.bind("<<ComboboxSelected>>", self._on_period_changed)

        self._refresh_toolbar()

    def _build_treeview(self) -> None:
        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True, padx=4, pady=4)

        cols = ("time_range", "break", "type_office", "note", "duration")
        self._tree = ttk.Treeview(
            frame,
            columns=cols,
            show="tree headings",
            selectmode="browse",
            style="TimeClock.Treeview",
        )

        self._tree.column("#0", width=310, minwidth=200, stretch=False)
        self._tree.heading("#0", text="Period / Date", anchor="w")

        self._tree.column("time_range", width=130,
                          minwidth=100, stretch=False, anchor="w")
        self._tree.heading("time_range", text="Time", anchor="w")

        self._tree.column("break", width=55, minwidth=40,
                          stretch=False, anchor="center")
        self._tree.heading("break", text="Break", anchor="center")

        self._tree.column("type_office", width=170,
                          minwidth=100, stretch=False, anchor="w")
        self._tree.heading("type_office", text="Type / Office", anchor="w")

        self._tree.column("note", width=180, minwidth=60,
                          stretch=True, anchor="w")
        self._tree.heading("note", text="Note", anchor="w")

        self._tree.column("duration", width=70, minwidth=50,
                          stretch=False, anchor="e")
        self._tree.heading("duration", text="Duration", anchor="e")

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

        self._btn_clock_in = ttk.Button(
            inner, text="▶  Clock In", style="Success.TButton",
            command=self._do_clock_in, width=14,
        )
        self._btn_clock_in.pack(side="left", padx=(0, 4))

        self._btn_clock_out = ttk.Button(
            inner, text="■  Clock Out", style="Danger.TButton",
            command=self._do_clock_out, width=14,
        )
        self._btn_clock_out.pack(side="left")

        ttk.Separator(inner, orient="vertical").pack(
            side="left", fill="y", padx=10, pady=2)

        self._btn_add = ttk.Button(
            inner, text="+ Add", command=self._do_add, width=10)
        self._btn_add.pack(side="left", padx=(0, 4))

        self._btn_edit = ttk.Button(
            inner, text="✏ Edit", command=self._do_edit, width=10)
        self._btn_edit.pack(side="left", padx=(0, 4))

        self._btn_delete = ttk.Button(
            inner, text="🗑 Delete", style="Danger.TButton",
            command=self._do_delete, width=10,
        )
        self._btn_delete.pack(side="left")

    def _bind_shortcuts(self) -> None:
        def _guard(fn: Callable) -> Callable:
            # type: ignore[assignment]
            def _handler(_e: tk.Event = None) -> None:
                try:
                    if self.winfo_exists():
                        fn()
                except Exception:
                    pass
            return _handler

        self.root.bind_all("<Control-n>", _guard(self._do_add), add=True)
        self.root.bind_all("<Control-e>", _guard(self._do_edit), add=True)
        self.root.bind_all("<Delete>",    _guard(self._do_delete), add=True)
        self.root.bind_all("<Control-d>", _guard(self._do_clock_out), add=True)
        self.root.bind_all("<F5>",        _guard(self._refresh), add=True)

    def _apply_tag_styles(self) -> None:
        c = COLORS.get("light", COLORS["light"])
        self._tree.tag_configure(
            "header", foreground=c["fg.muted"], font=("Helvetica", 9, "bold")
        )
        self._tree.tag_configure(
            "day_header", foreground=c["fg.muted"], font=("Helvetica", 9, "bold")
        )
        self._tree.tag_configure("inprogress", background=c["inprogress_bg"])
        self._tree.tag_configure("overtime", foreground=c["overtime"])

        style = ttk.Style()
        style.configure("TimeClock.Treeview", font=(
            "Consolas", 10), rowheight=22)
        style.configure("TimeClock.Treeview.Heading",
                        font=("Helvetica", 9, "bold"))

    # ─────────────────────────── Toolbar / View Mode ────────────────────────

    def _set_view_mode(self, mode: str) -> None:
        if self._view_mode == mode:
            return
        self._view_mode = mode
        self.settings.set("view_mode", mode)
        self._refresh_toolbar()
        self._refresh_tree()

    def _refresh_toolbar(self) -> None:
        is_week = self._view_mode == "week"
        if is_week:
            self._frm_month.pack_forget()
            self._frm_week.pack(side="left")
            self._update_week_label()
            self._btn_week.config(style="Accent.TButton")
            self._btn_month.config(style="TButton")
        else:
            self._frm_week.pack_forget()
            self._frm_month.pack(side="left")
            self._btn_month.config(style="Accent.TButton")
            self._btn_week.config(style="TButton")

    def _update_week_label(self) -> None:
        week_end = self._selected_week_start + timedelta(days=6)
        self._lbl_week_range.config(
            text=f"{to_display_date(self._selected_week_start)} – {to_display_date(week_end)}"
        )

    def _prev_week(self) -> None:
        self._selected_week_start -= timedelta(days=7)
        self._update_week_label()
        self._refresh_tree()

    def _next_week(self) -> None:
        self._selected_week_start += timedelta(days=7)
        self._update_week_label()
        self._refresh_tree()

    def _on_period_changed(self, _event: object = None) -> None:
        try:
            self._selected_year = int(self._var_year.get())
        except ValueError:
            pass
        month_name = self._var_month.get()
        if month_name in _MONTH_NAMES:
            idx = _MONTH_NAMES.index(month_name)
            if idx > 0:
                self._selected_month = idx
        self._refresh_tree()

    # ─────────────────────────── Header Bar ─────────────────────────────────

    def _refresh_header(self) -> None:
        today = date.today()
        now_t = _now_time()
        targets = self.model.get_work_day_targets()
        exceptions = _build_exc_dict(
            self.model.get_date_exceptions(today.year))

        target_h = get_daily_target(today, targets, exceptions)
        worked_h = sum(
            get_record_duration(r, today, now_t)
            for r in self.model.get_records_by_date(today)
        )
        remaining = target_h - worked_h

        self._lbl_today.config(text=f"Today: {to_display_date(today)}")
        self._lbl_target.config(text=f"Target: {_fmt_h(target_h)}")

        c = COLORS.get("light", COLORS["light"])
        if target_h == 0:
            self._lbl_remaining.config(
                text="Day off", foreground=c["fg.muted"])
        elif remaining > 0:
            self._lbl_remaining.config(
                text=f"{_fmt_h(remaining)} left", foreground=c["warning"])
        elif remaining == 0:
            self._lbl_remaining.config(text="✓ Done", foreground=c["success"])
        else:
            self._lbl_remaining.config(
                text=f"⏎ +{_fmt_h(abs(remaining))} overtime",
                foreground=c["overtime"],
            )

    # ─────────────────────────── Tree Population ────────────────────────────

    def _clear_tree(self) -> None:
        children = self._tree.get_children()
        if children:
            self._tree.delete(*children)

    def _refresh_tree(self) -> None:
        self._clear_tree()
        if self._view_mode == "week":
            self._populate_week()
        else:
            self._populate_month()

    def _populate_month(self) -> None:
        year = self._selected_year
        month = self._selected_month
        today = date.today()
        now_t = _now_time()

        records = self.model.get_records_for_period(year, month)
        targets = self.model.get_work_day_targets()
        exceptions = _build_exc_dict(self.model.get_date_exceptions(year))
        period_start, period_end = get_month_range(date(year, month, 1))
        overtime_rate: float = self.settings.get("overtime_rate") or 1.0

        balance = calculate_period_balance(
            records, period_start, period_end, targets, exceptions,
            overtime_rate=overtime_rate, today=today, now_time=now_t,
        )

        month_text = (
            f"── {_MONTH_NAMES[month]} {year}"
            f"  ({_fmt_h(balance['worked_hours'])} / {_fmt_h(balance['target_hours'])}) ──"
        )
        month_node = self._tree.insert(
            "", "end", text=month_text,
            values=("", "", "", "", ""),
            tags=("header",), open=True,
        )

        records_by_date: dict[date, list[TimeRecord]] = {}
        for rec in records:
            records_by_date.setdefault(rec.date, []).append(rec)

        total_days = (period_end - period_start).days + 1
        for offset in range(total_days):
            day = period_end - timedelta(days=offset)
            day_recs = records_by_date.get(day, [])
            if not day_recs and day != today:
                continue
            day_recs_sorted = sorted(day_recs, key=lambda r: r.start_time)
            day_worked = sum(get_record_duration(r, today, now_t)
                             for r in day_recs)
            day_target = get_daily_target(day, targets, exceptions)
            is_overtime_day = day_worked > day_target > 0

            day_node = self._insert_day_header(
                month_node, day, day_worked, day_target)
            for rec in day_recs_sorted:
                self._insert_record_row(
                    day_node, rec, today, now_t, is_overtime_day)

    def _populate_week(self) -> None:
        week_start = self._selected_week_start
        week_end = week_start + timedelta(days=6)
        today = date.today()
        now_t = _now_time()

        # Fetch records — may span two calendar months
        records: list[TimeRecord] = []
        seen_ids: set[int] = set()
        for fetch_date in {week_start, week_end}:
            for rec in self.model.get_records_for_period(fetch_date.year, fetch_date.month):
                rid = rec.id
                if rid not in seen_ids and week_start <= rec.date <= week_end:
                    seen_ids.add(rid)  # type: ignore[arg-type]
                    records.append(rec)

        targets = self.model.get_work_day_targets()
        exceptions = _build_exc_dict(
            self.model.get_date_exceptions(week_start.year))
        if week_end.year != week_start.year:
            exceptions.update(_build_exc_dict(
                self.model.get_date_exceptions(week_end.year)))
        overtime_rate: float = self.settings.get("overtime_rate") or 1.0

        balance = calculate_period_balance(
            records, week_start, week_end, targets, exceptions,
            overtime_rate=overtime_rate, today=today, now_time=now_t,
        )

        week_text = (
            f"── Week  {to_display_date(week_start)} – {to_display_date(week_end)}"
            f"  ({_fmt_h(balance['worked_hours'])} / {_fmt_h(balance['target_hours'])}) ──"
        )
        week_node = self._tree.insert(
            "", "end", text=week_text,
            values=("", "", "", "", ""),
            tags=("header",), open=True,
        )

        records_by_date: dict[date, list[TimeRecord]] = {}
        for rec in records:
            records_by_date.setdefault(rec.date, []).append(rec)

        for i in range(7):
            day = week_start + timedelta(days=i)
            day_recs = sorted(records_by_date.get(day, []),
                              key=lambda r: r.start_time)
            day_worked = sum(get_record_duration(r, today, now_t)
                             for r in day_recs)
            day_target = get_daily_target(day, targets, exceptions)
            is_overtime_day = day_worked > day_target > 0

            day_node = self._insert_day_header(
                week_node, day, day_worked, day_target)
            for rec in day_recs:
                self._insert_record_row(
                    day_node, rec, today, now_t, is_overtime_day)

        bal = balance["balance"]
        sign = "+" if bal >= 0 else "-"
        self._tree.insert(
            "", "end",
            text=f"── Balance: {sign}{_fmt_h(abs(bal))} ──",
            values=("", "", "", "", ""),
            tags=("header",),
        )

    def _insert_day_header(
        self, parent: str, day: date, worked: float, target: float
    ) -> str:
        day_name = _DAY_NAMES[day.weekday()]
        disp = to_display_date(day)
        hebrew = _safe_hebrew(day)
        heb_part = f" / {hebrew}" if hebrew else ""
        label = f"── {day_name}, {disp}{heb_part}  ({_fmt_h(worked)} / {_fmt_h(target)}) ──"
        return self._tree.insert(
            parent, "end",
            text=label,
            values=("", "", "", "", ""),
            tags=("day_header",),
            open=True,
        )

    def _insert_record_row(
        self,
        parent: str,
        rec: TimeRecord,
        today: date,
        now_t: time,
        is_overtime: bool = False,
    ) -> None:
        start_str = time_to_str(rec.start_time)
        if rec.end_time is not None:
            time_range = f"{start_str} – {time_to_str(rec.end_time)}"
        else:
            time_range = f"{start_str} – …"

        break_str = f"{rec.break_minutes}m" if rec.break_minutes > 0 else "—"

        type_label = _WORK_TYPE_LABELS.get(rec.work_type, str(rec.work_type))
        if rec.work_type == WorkType.IN_SITE and rec.office:
            type_office = f"{type_label} / {rec.office}"
        else:
            type_office = type_label

        hours = get_record_duration(rec, today, now_t)
        dur_str = _fmt_h(hours) if (
            rec.end_time is not None or rec.date == today) else "—"
        note = rec.note or ""

        if rec.is_open:
            tags: tuple[str, ...] = ("inprogress",)
        elif is_overtime:
            tags = ("overtime",)
        else:
            tags = ()

        self._tree.insert(
            parent, "end",
            text="",
            iid=f"rec_{rec.id}",
            values=(time_range, break_str, type_office, note, dur_str),
            tags=tags,
        )

    # ─────────────────────────── Refresh ────────────────────────────────────

    def _refresh(self, **_kw: object) -> None:
        self._refresh_header()
        self._refresh_tree()
        self._update_button_states()

    def _on_event(self, **_kw: object) -> None:
        self._refresh()
        if self.model.get_open_records() and self._after_id is None:
            self._start_auto_refresh()

    # ─────────────────────────── Auto-refresh ───────────────────────────────

    def _start_auto_refresh(self) -> None:
        if self._after_id is not None:
            return
        self._after_id = self.root.after(60_000, self._auto_refresh)

    def _auto_refresh(self) -> None:
        self._after_id = None
        if self.model.get_open_records():
            self._refresh_header()
            self._refresh_tree()
            self._after_id = self.root.after(60_000, self._auto_refresh)

    def _cancel_auto_refresh(self) -> None:
        if self._after_id is not None:
            try:
                self.root.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    # ─────────────────────────── Button State ───────────────────────────────

    def _update_button_states(self) -> None:
        has_open = bool(self.model.get_open_records())
        self._btn_clock_in.config(
            state="normal" if not has_open else "disabled")
        self._btn_clock_out.config(state="normal" if has_open else "disabled")
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

    def _get_selected_record(self) -> Optional[TimeRecord]:
        rec_id = self._get_selected_record_id()
        return self.model.get_record_by_id(rec_id) if rec_id is not None else None

    # ─────────────────────────── Tree Callbacks ─────────────────────────────

    # type: ignore[type-arg]
    def _on_double_click(self, event: tk.Event) -> None:
        iid = self._tree.identify_row(event.y)
        if iid and iid.startswith("rec_"):
            self._tree.selection_set(iid)
            self._do_edit()

    def _on_tree_select(self, _event: object = None) -> None:
        state = "normal" if self._get_selected_record_id() is not None else "disabled"
        self._btn_edit.config(state=state)
        self._btn_delete.config(state=state)

    # ─────────────────────────── Actions ────────────────────────────────────

    def _do_clock_in(self) -> None:
        result = self.controller.clock_in()
        if not result.ok:
            if "OPEN_RECORD_EXISTS" in result.errors:
                if messagebox.askyesno(
                    "Open Record Exists",
                    "An open record already exists.\nStart a new clock-in anyway?",
                    parent=self,
                ):
                    result = self.controller.clock_in(force=True)
                else:
                    return
        if result.ok:
            self._update_button_states()
            self._start_auto_refresh()
        elif result.errors:
            messagebox.showerror("Clock In Failed", "\n".join(
                result.errors), parent=self)

    def _do_clock_out(self) -> None:
        result = self.controller.clock_out()
        if not result.ok:
            if "MULTIPLE_OPEN_RECORDS" in result.errors:
                self._pick_record_to_close()
                return
            messagebox.showerror("Clock Out Failed",
                                 "\n".join(result.errors), parent=self)
            return
        self._update_button_states()
        if not self.model.get_open_records():
            self._cancel_auto_refresh()

    def _pick_record_to_close(self) -> None:
        open_recs = self.model.get_open_records()
        if not open_recs:
            return

        dlg = tk.Toplevel(self)
        dlg.title("Select Record to Clock Out")
        dlg.resizable(False, False)
        dlg.transient(self.winfo_toplevel())
        dlg.grab_set()

        ttk.Label(
            dlg,
            text="Multiple open records — select one to clock out:",
            padding=(12, 10, 12, 4),
        ).pack(anchor="w")

        lb_frame = ttk.Frame(dlg)
        lb_frame.pack(fill="x", padx=12, pady=4)
        lb = tk.Listbox(lb_frame, selectmode="single",
                        height=min(len(open_recs), 8), width=52)
        lb.pack(fill="x")
        for rec in open_recs:
            line = f"{to_display_date(rec.date)}  {time_to_str(rec.start_time)} – open"
            if rec.note:
                line += f"   [{rec.note[:32]}]"
            lb.insert("end", line)
        lb.selection_set(0)

        btn_frame = ttk.Frame(dlg)
        btn_frame.pack(padx=12, pady=(8, 12))

        def _confirm() -> None:
            sel = lb.curselection()
            if not sel:
                return
            chosen = open_recs[sel[0]]
            dlg.destroy()
            res = self.controller.clock_out(record_id=chosen.id)
            if res.ok:
                self._update_button_states()
                if not self.model.get_open_records():
                    self._cancel_auto_refresh()
            else:
                messagebox.showerror("Clock Out Failed",
                                     "\n".join(res.errors), parent=self)

        ttk.Button(
            btn_frame, text="Clock Out", style="Danger.TButton", command=_confirm
        ).pack(side="left", padx=(0, 6))
        ttk.Button(btn_frame, text="Cancel",
                   command=dlg.destroy).pack(side="left")
        dlg.wait_window()

    def _do_add(self) -> None:
        try:
            from views.time_record_dialog import TimeRecordDialog
        except ImportError:
            messagebox.showinfo(
                "Not Available", "Time record dialog is not yet available.", parent=self
            )
            return
        TimeRecordDialog(
            self, controller=self.controller,
            settings=self.settings, record=None,
        )

    def _do_edit(self) -> None:
        rec = self._get_selected_record()
        if rec is None:
            return
        try:
            from views.time_record_dialog import TimeRecordDialog
        except ImportError:
            messagebox.showinfo(
                "Not Available", "Time record dialog is not yet available.", parent=self
            )
            return
        TimeRecordDialog(
            self, controller=self.controller,
            settings=self.settings, record=rec,
        )

    def _do_delete(self) -> None:
        rec_id = self._get_selected_record_id()
        if rec_id is None:
            return
        if not messagebox.askyesno(
            "Confirm Delete",
            "Permanently delete this time record?",
            icon="warning",
            parent=self,
        ):
            return
        result = self.controller.delete_record(rec_id)
        if not result.ok:
            messagebox.showerror("Delete Failed", "\n".join(
                result.errors), parent=self)

    # ─────────────────────────── Lifecycle ──────────────────────────────────

    def _on_destroy(self, _event: object = None) -> None:
        self._cancel_auto_refresh()
        for unsub in self._unsubs:
            try:
                unsub()
            except Exception:
                pass
        self._unsubs.clear()
