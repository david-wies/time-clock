"""Add / Edit Time Record dialog."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from datetime import date, time, datetime
from typing import Optional

from controllers.time_clock_controller import TimeClockController
from core.timeutil import duration
from domain.enums import WorkType
from domain.types import TimeRecord
from settings import SettingsManager
from views.date_picker import make_date_picker

_OVERNIGHT_BG = "#FEF3C7"

_WORK_TYPE_OPTIONS: list[tuple[WorkType, str]] = [
    (WorkType.IN_SITE, "In Site"),
    (WorkType.ROAD, "Road"),
    (WorkType.REMOTE, "Remote"),
]


def _parse_hhmm(s: str) -> time:
    s = s.strip()
    parts = s.split(":")
    if len(parts) != 2:
        raise ValueError(f"Expected HH:MM, got {s!r}")
    h, m = int(parts[0]), int(parts[1])
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"Time out of range: {h}:{m}")
    return time(h, m)


def _break_to_minutes(s: str) -> int:
    s = s.strip()
    if not s:
        return 0
    t = _parse_hhmm(s)
    return t.hour * 60 + t.minute


def _minutes_to_hhmm(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    return f"{h:02d}:{m:02d}"


def _preset_label(minutes: int) -> str:
    if minutes % 60 == 0:
        return f"{minutes // 60}h"
    h, m = divmod(minutes, 60)
    return f"{m}m" if h == 0 else f"{h}h {m}m"


class TimeRecordDialog(tk.Toplevel):

    def __init__(
        self,
        parent,
        controller: TimeClockController,
        settings: SettingsManager,
        record: Optional[TimeRecord] = None,
        **_kwargs,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._settings = settings
        self._record = record

        editing = record is not None
        self.title("Edit Time Record" if editing else "Add Time Record")
        self.resizable(False, False)
        self.minsize(420, 380)
        self.transient(parent)
        self.grab_set()

        self._build_ui()
        self._populate(record)
        self._update_office_state()
        self._update_duration()

        self.wait_window(self)

    # ─────────────────────────── UI Construction ────────────────────────────

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=(16, 12, 16, 8))
        outer.pack(fill="both", expand=True)

        # ── Date ──────────────────────────────────────────────────────────────
        date_row = ttk.Frame(outer)
        date_row.pack(fill="x", pady=(0, 6))
        ttk.Label(date_row, text="Date:", width=8,
                  anchor="e").pack(side="left")

        dp_result = make_date_picker(date_row)
        if isinstance(dp_result, tuple):
            self._date_widget, self._get_date, self._set_date = dp_result
        else:
            self._date_widget = dp_result
            self._get_date = dp_result.get_date
            self._set_date = dp_result.set_date
        self._date_widget.pack(side="left", padx=(4, 0))

        # ── Start / End ───────────────────────────────────────────────────────
        self._time_row = ttk.Frame(outer)
        self._time_row.pack(fill="x", pady=(0, 6))
        ttk.Label(self._time_row, text="Start:",
                  width=8, anchor="e").pack(side="left")
        self._var_start = tk.StringVar()
        ttk.Entry(self._time_row, textvariable=self._var_start, width=8).pack(
            side="left", padx=(4, 12)
        )
        ttk.Label(self._time_row, text="End:").pack(side="left")
        self._var_end = tk.StringVar()
        ttk.Entry(self._time_row, textvariable=self._var_end, width=8).pack(
            side="left", padx=(4, 0)
        )

        # ── Overnight warning (hidden until needed) ───────────────────────────
        self._frm_overnight = tk.Frame(outer, background=_OVERNIGHT_BG)
        tk.Label(
            self._frm_overnight,
            text="Overnight shift — end time is next day",
            background=_OVERNIGHT_BG,
            anchor="w",
            padx=6,
            pady=3,
        ).pack(fill="x")

        # ── Break + Net duration ──────────────────────────────────────────────
        break_row = ttk.Frame(outer)
        break_row.pack(fill="x", pady=(0, 4))
        ttk.Label(break_row, text="Break:", width=8,
                  anchor="e").pack(side="left")
        self._var_break = tk.StringVar(value="00:00")
        ttk.Entry(break_row, textvariable=self._var_break, width=8).pack(
            side="left", padx=(4, 6)
        )
        ttk.Label(break_row, text="HH:MM unpaid", foreground="gray").pack(
            side="left", padx=(0, 10)
        )
        self._lbl_duration = ttk.Label(break_row, text="Net: --")
        self._lbl_duration.pack(side="left")

        # ── Break preset buttons ──────────────────────────────────────────────
        presets_row = ttk.Frame(outer)
        presets_row.pack(fill="x", pady=(0, 8))
        ttk.Label(presets_row, text="", width=8).pack(side="left")
        presets: list[int] = self._settings.get(
            "break_presets") or [15, 30, 45, 60]
        for mins in presets:
            ttk.Button(
                presets_row,
                text=_preset_label(mins),
                width=5,
                command=lambda m=mins: self._apply_break_preset(m),
            ).pack(side="left", padx=(0, 4))

        # ── Work type ─────────────────────────────────────────────────────────
        type_row = ttk.Frame(outer)
        type_row.pack(fill="x", pady=(0, 6))
        ttk.Label(type_row, text="Type:", width=8,
                  anchor="e").pack(side="left")
        self._var_work_type = tk.StringVar(value=str(WorkType.IN_SITE))
        for wt, label in _WORK_TYPE_OPTIONS:
            ttk.Radiobutton(
                type_row,
                text=label,
                variable=self._var_work_type,
                value=str(wt),
                command=self._update_office_state,
            ).pack(side="left", padx=(4, 0))

        # ── Office ────────────────────────────────────────────────────────────
        office_row = ttk.Frame(outer)
        office_row.pack(fill="x", pady=(0, 6))
        ttk.Label(office_row, text="Office:", width=8,
                  anchor="e").pack(side="left")
        offices: list[str] = self._settings.get("offices") or []
        self._var_office = tk.StringVar()
        self._cbo_office = ttk.Combobox(
            office_row,
            textvariable=self._var_office,
            values=offices,
            state="readonly",
            width=24,
        )
        self._cbo_office.pack(side="left", padx=(4, 0))

        # ── Note ──────────────────────────────────────────────────────────────
        note_row = ttk.Frame(outer)
        note_row.pack(fill="x", pady=(0, 10))
        ttk.Label(note_row, text="Note:", width=8,
                  anchor="e").pack(side="left")
        vcmd = (self.register(self._validate_note), "%P")
        self._var_note = tk.StringVar()
        ttk.Entry(
            note_row,
            textvariable=self._var_note,
            width=38,
            validate="key",
            validatecommand=vcmd,
        ).pack(side="left", padx=(4, 0), fill="x", expand=True)

        # ── Error label ───────────────────────────────────────────────────────
        self._lbl_error = ttk.Label(
            outer, text="", foreground="red", wraplength=388, justify="left"
        )
        self._lbl_error.pack(fill="x", pady=(0, 4))

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_row = ttk.Frame(outer)
        btn_row.pack(fill="x", pady=(4, 0))
        ttk.Button(btn_row, text="Cancel", command=self.destroy).pack(
            side="right", padx=(6, 0)
        )
        ttk.Button(btn_row, text="Save",
                   command=self._on_save).pack(side="right")

        # ── Live-update traces ────────────────────────────────────────────────
        for var in (self._var_start, self._var_end, self._var_break):
            var.trace_add("write", lambda *_: self._update_duration())

    # ─────────────────────────── Data Population ────────────────────────────

    def _populate(self, record: Optional[TimeRecord]) -> None:
        if record is None:
            self._set_date(date.today())
            self._var_start.set(datetime.now().strftime("%H:%M"))
            self._var_end.set("")
            self._var_break.set("00:00")
            default_wt = self._settings.get(
                "default_work_type") or str(WorkType.IN_SITE)
            self._var_work_type.set(str(default_wt))
            offices: list[str] = self._settings.get("offices") or []
            if offices:
                self._var_office.set(offices[0])
            self._var_note.set("")
        else:
            self._set_date(record.date)
            self._var_start.set(record.start_time.strftime("%H:%M"))
            self._var_end.set(record.end_time.strftime(
                "%H:%M") if record.end_time else "")
            self._var_break.set(_minutes_to_hhmm(record.break_minutes))
            self._var_work_type.set(str(record.work_type))
            self._var_office.set(record.office or "")
            self._var_note.set(record.note or "")

    # ─────────────────────────── Widget Callbacks ────────────────────────────

    def _validate_note(self, proposed: str) -> bool:
        return len(proposed) <= 500

    def _apply_break_preset(self, minutes: int) -> None:
        self._var_break.set(_minutes_to_hhmm(minutes))

    def _update_office_state(self) -> None:
        wt = self._var_work_type.get()
        self._cbo_office.config(
            state="readonly" if wt == str(WorkType.IN_SITE) else "disabled"
        )

    def _update_duration(self) -> None:
        start_s = self._var_start.get().strip()
        end_s = self._var_end.get().strip()
        break_s = self._var_break.get().strip()

        # Overnight warning
        show_overnight = False
        if start_s and end_s:
            try:
                show_overnight = _parse_hhmm(end_s) < _parse_hhmm(start_s)
            except ValueError:
                pass

        is_mapped = self._frm_overnight.winfo_ismapped()
        if show_overnight and not is_mapped:
            self._frm_overnight.pack(
                fill="x", pady=(0, 4), after=self._time_row)
        elif not show_overnight and is_mapped:
            self._frm_overnight.pack_forget()

        # Net duration
        try:
            t_start = _parse_hhmm(start_s)
            break_m = _break_to_minutes(break_s)
            if end_s:
                t_end = _parse_hhmm(end_s)
            else:
                now = datetime.now()
                t_end = time(now.hour, now.minute)
            hours = duration(t_start, t_end, break_m)
            self._lbl_duration.config(text=f"Net: {hours:.1f}h")
        except (ValueError, TypeError):
            self._lbl_duration.config(text="Net: --")

    # ─────────────────────────── Save ────────────────────────────────────────

    def _on_save(self) -> None:
        self._lbl_error.config(text="")
        field_errors: list[str] = []

        try:
            rec_date: Optional[date] = self._get_date()
        except Exception:
            field_errors.append("Invalid date.")
            rec_date = None

        start_time: Optional[time] = None
        try:
            start_time = _parse_hhmm(self._var_start.get())
        except ValueError:
            field_errors.append(
                "Start time must be in HH:MM format (00:00–23:59).")

        end_time: Optional[time] = None
        end_s = self._var_end.get().strip()
        if end_s:
            try:
                end_time = _parse_hhmm(end_s)
            except ValueError:
                field_errors.append(
                    "End time must be in HH:MM format (00:00–23:59).")

        try:
            break_minutes = _break_to_minutes(self._var_break.get())
        except ValueError:
            field_errors.append("Break must be in HH:MM format (e.g. 00:30).")
            break_minutes = 0

        if field_errors:
            self._lbl_error.config(text="\n".join(field_errors))
            return

        wt_val = self._var_work_type.get()
        try:
            work_type = WorkType(wt_val)
        except ValueError:
            self._lbl_error.config(text=f"Invalid work type: {wt_val!r}")
            return

        office: Optional[str] = None
        if work_type == WorkType.IN_SITE:
            o = self._var_office.get().strip()
            office = o or None

        note_s = self._var_note.get().strip()
        note: Optional[str] = note_s or None

        record = TimeRecord(
            id=self._record.id if self._record is not None else None,
            date=rec_date,
            start_time=start_time,
            end_time=end_time,
            break_minutes=break_minutes,
            work_type=work_type,
            office=office,
            note=note,
        )

        result = self._controller.save_record(record)
        if result.ok:
            self.destroy()
        else:
            self._lbl_error.config(text="\n".join(result.errors))
