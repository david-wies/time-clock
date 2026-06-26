"""Date picker: tkcalendar.DateEntry wrapper with pure-Tk fallback."""

import calendar
from datetime import date
from tkinter import ttk, Toplevel, StringVar
from typing import Optional, Callable


def make_date_picker(parent, **kwargs):
    """Creates a date picker widget. Returns (widget, get_date, set_date)."""
    try:
        from tkcalendar import DateEntry
        picker = DateEntry(parent, date_pattern="yyyy-MM-dd", **kwargs)
        return picker, lambda: picker.get_date(), lambda d: picker.set_date(d)
    except ImportError:
        return _FallbackDatePicker(parent, **kwargs)


class _FallbackDatePicker(ttk.Frame):
    """Pure-tkinter fallback date picker with popup calendar grid."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent)
        self._var = StringVar(value=date.today().isoformat())
        self._entry = ttk.Entry(self, textvariable=self._var, width=12)
        self._btn = ttk.Button(self, text="📅", width=3, command=self._popup)
        self._entry.pack(side="left")
        self._btn.pack(side="left", padx=(2, 0))

    def get_date(self) -> date:
        return date.fromisoformat(self._var.get())

    def set_date(self, d: date) -> None:
        self._var.set(d.isoformat())

    def _popup(self) -> None:
        top = Toplevel(self)
        top.title("Select Date")
        top.resizable(False, False)

        current = self.get_date()
        cal_month, cal_year = current.month, current.year

        nav = ttk.Frame(top)
        nav.pack(pady=4)
        lbl = ttk.Label(nav, text="", font=("Helvetica", 10, "bold"))
        lbl.pack(side="left", padx=8)

        def rebuild(delta_month: int = 0):
            nonlocal cal_month, cal_year
            cal_month += delta_month
            if cal_month < 1:
                cal_month, cal_year = 12, cal_year - 1
            elif cal_month > 12:
                cal_month, cal_year = 1, cal_year + 1
            lbl.config(text=f"{calendar.month_name[cal_month]} {cal_year}")

            for w in body.winfo_children():
                w.destroy()

            cal_data = calendar.monthcalendar(cal_year, cal_month)
            for row_idx, week in enumerate(cal_data):
                for col_idx, day in enumerate(week):
                    if day == 0:
                        ttk.Label(body, text="").grid(row=row_idx, column=col_idx, padx=2, pady=1)
                    else:
                        btn = ttk.Button(body, text=str(day), width=3,
                                         command=lambda d=date(cal_year, cal_month, day): _select(d))
                        btn.grid(row=row_idx, column=col_idx, padx=1, pady=1)

        def _select(d: date) -> None:
            self.set_date(d)
            top.destroy()

        ttk.Button(nav, text="<", width=3, command=lambda: rebuild(-1)).pack(side="left", padx=(0, 4))
        ttk.Button(nav, text=">", width=3, command=lambda: rebuild(1)).pack(side="left", padx=(4, 0))

        days_header = ttk.Frame(top)
        days_header.pack()
        for i, dname in enumerate(["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]):
            ttk.Label(days_header, text=dname, width=4, anchor="center",
                      font=("Helvetica", 8, "bold")).grid(row=0, column=i, padx=1)

        body = ttk.Frame(top)
        body.pack(pady=4)
        rebuild(0)

        btn_frame = ttk.Frame(top)
        btn_frame.pack(pady=4)
        ttk.Button(btn_frame, text="Cancel", command=top.destroy).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="Select", command=lambda: _select(self.get_date())).pack(side="left", padx=4)

        top.transient(self.winfo_toplevel())
        top.grab_set()
        self.wait_window(top)
