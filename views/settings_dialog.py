"""Settings dialog — all application preferences in one place."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from datetime import date
from typing import Callable, Optional

from core.events import EventBus, Event
from core.timeutil import to_display_date, date_to_iso, iso_to_date
from domain.enums import WorkType
from models.sickness_model import SicknessModel
from models.time_clock_model import TimeClockModel
from models.vacation_model import VacationModel
from settings import SettingsManager
from views.date_picker import make_date_picker

_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

_COUNTRIES = [
    "Australia", "Austria", "Belgium", "Brazil", "Canada",
    "China", "Czech", "Denmark", "Finland", "France",
    "Germany", "Greece", "Hungary", "India", "Ireland",
    "Israel", "Italy", "Japan", "Mexico", "Netherlands",
    "NewZealand", "Norway", "Poland", "Portugal", "Russia",
    "SaudiArabia", "Slovakia", "Spain", "Sweden", "Switzerland",
    "Turkey", "Ukraine", "UnitedKingdom", "UnitedStates",
]

_WORK_TYPE_OPTIONS: list[tuple[WorkType, str]] = [
    (WorkType.IN_SITE, "In Site"),
    (WorkType.ROAD, "Road"),
    (WorkType.REMOTE, "Remote"),
]

_OVERTIME_PERIODS = ["week", "month", "year"]


class SettingsDialog(tk.Toplevel):

    def __init__(
        self,
        parent,
        settings: SettingsManager,
        model_tc: TimeClockModel,
        model_vacation: VacationModel,
        model_sickness: SicknessModel,
        bus: EventBus,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._model_tc = model_tc
        self._model_vacation = model_vacation
        self._model_sickness = model_sickness
        self._bus = bus

        self.title("Settings")
        self.minsize(600, 560)
        self.resizable(True, True)
        self.transient(parent)
        self.grab_set()

        self._build_ui()

        self.wait_window(self)

    # ─────────────────────────── Main UI ────────────────────────────────────

    def _build_ui(self) -> None:
        main = ttk.Frame(self, padding=(8, 8, 8, 4))
        main.pack(fill="both", expand=True)

        self._notebook = ttk.Notebook(main)
        self._notebook.pack(fill="both", expand=True)

        tab_tc = ttk.Frame(self._notebook)
        self._notebook.add(tab_tc, text="Time Clock")
        self._build_tab_timeclock(tab_tc)

        tab_exc = ttk.Frame(self._notebook)
        self._notebook.add(tab_exc, text="Date Exceptions")
        self._build_tab_exceptions(tab_exc)

        tab_vac = ttk.Frame(self._notebook)
        self._notebook.add(tab_vac, text="Vacation")
        self._build_tab_vacation(tab_vac)

        tab_sick = ttk.Frame(self._notebook)
        self._notebook.add(tab_sick, text="Sickness")
        self._build_tab_sickness(tab_sick)

        tab_disp = ttk.Frame(self._notebook)
        self._notebook.add(tab_disp, text="Display")
        self._build_tab_display(tab_disp)

        btn_row = ttk.Frame(main)
        btn_row.pack(fill="x", pady=(8, 0))
        ttk.Button(btn_row, text="Cancel", command=self.destroy).pack(side="right", padx=(6, 0))
        ttk.Button(btn_row, text="Save", style="Accent.TButton", command=self._on_save).pack(side="right")

    # ─────────────────────────── Tab 1: Time Clock ──────────────────────────

    def _build_tab_timeclock(self, parent: ttk.Frame) -> None:
        canvas = tk.Canvas(parent, highlightthickness=0)
        vsb = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        inner = ttk.Frame(canvas)
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win_id, width=e.width))

        def _on_mousewheel(e: tk.Event) -> None:
            if e.num == 4:
                canvas.yview_scroll(-1, "units")
            elif e.num == 5:
                canvas.yview_scroll(1, "units")
            else:
                canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

        def _bind_mw(_e=None) -> None:
            canvas.bind_all("<MouseWheel>", _on_mousewheel)
            canvas.bind_all("<Button-4>", _on_mousewheel)
            canvas.bind_all("<Button-5>", _on_mousewheel)

        def _unbind_mw(_e=None) -> None:
            canvas.unbind_all("<MouseWheel>")
            canvas.unbind_all("<Button-4>")
            canvas.unbind_all("<Button-5>")

        canvas.bind("<Enter>", _bind_mw)
        canvas.bind("<Leave>", _unbind_mw)

        pad = {"padx": 10, "pady": 4}

        # ── Daily Work Hours ──────────────────────────────────────────────────
        lf_days = ttk.LabelFrame(inner, text="Daily Work Hours", padding=(8, 4, 8, 8))
        lf_days.pack(fill="x", **pad)

        targets = self._model_tc.get_work_day_targets()
        self._day_vars: list[tuple[tk.BooleanVar, tk.StringVar]] = []

        for i, day_name in enumerate(_DAY_NAMES):
            row = ttk.Frame(lf_days)
            row.pack(fill="x", pady=1)
            hours = targets.get(i)
            enabled = hours is not None and hours > 0.0
            chk_var = tk.BooleanVar(value=enabled)
            hrs_var = tk.StringVar(value=f"{hours:.1f}" if hours else "8.0")
            entry = ttk.Entry(row, textvariable=hrs_var, width=6)

            def _toggle(cv=chk_var, ent=entry) -> None:
                ent.config(state="normal" if cv.get() else "disabled")

            ttk.Checkbutton(row, text=day_name, variable=chk_var, width=12, command=_toggle).pack(side="left")
            entry.pack(side="left", padx=(4, 2))
            ttk.Label(row, text="h").pack(side="left")
            entry.config(state="normal" if enabled else "disabled")
            self._day_vars.append((chk_var, hrs_var))

        # ── Offices ───────────────────────────────────────────────────────────
        lf_offices = ttk.LabelFrame(inner, text="Offices", padding=(8, 4, 8, 8))
        lf_offices.pack(fill="x", **pad)

        list_frame = ttk.Frame(lf_offices)
        list_frame.pack(fill="x")
        offices: list[str] = list(self._settings.get("offices") or [])
        self._lb_offices = tk.Listbox(list_frame, height=4, selectmode="single", exportselection=False)
        for o in offices:
            self._lb_offices.insert("end", o)
        osb = ttk.Scrollbar(list_frame, orient="vertical", command=self._lb_offices.yview)
        self._lb_offices.configure(yscrollcommand=osb.set)
        self._lb_offices.pack(side="left", fill="x", expand=True)
        osb.pack(side="left", fill="y")

        office_btns = ttk.Frame(lf_offices)
        office_btns.pack(fill="x", pady=(4, 0))
        ttk.Button(office_btns, text="Add", command=self._office_add).pack(side="left", padx=(0, 4))
        ttk.Button(office_btns, text="Edit", command=self._office_edit).pack(side="left", padx=(0, 4))
        ttk.Button(office_btns, text="Remove", command=self._office_remove).pack(side="left")

        # ── Break Presets ─────────────────────────────────────────────────────
        lf_break = ttk.LabelFrame(inner, text="Break Presets (minutes)", padding=(8, 4, 8, 8))
        lf_break.pack(fill="x", **pad)

        presets: list[int] = list(self._settings.get("break_presets") or [15, 30, 45, 60])
        while len(presets) < 4:
            presets.append(0)
        self._break_vars: list[tk.StringVar] = []
        bp_row = ttk.Frame(lf_break)
        bp_row.pack(fill="x")
        for i in range(4):
            v = tk.StringVar(value=str(presets[i]))
            ttk.Label(bp_row, text=f"Preset {i + 1}:").pack(side="left", padx=(0, 2))
            ttk.Entry(bp_row, textvariable=v, width=5).pack(side="left", padx=(0, 12))
            self._break_vars.append(v)

        # ── Default Work Type ─────────────────────────────────────────────────
        lf_wtype = ttk.LabelFrame(inner, text="Default Work Type", padding=(8, 4, 8, 8))
        lf_wtype.pack(fill="x", **pad)

        self._var_work_type = tk.StringVar(
            value=str(self._settings.get("default_work_type") or WorkType.REMOTE)
        )
        wt_row = ttk.Frame(lf_wtype)
        wt_row.pack(fill="x")
        for wt, label in _WORK_TYPE_OPTIONS:
            ttk.Radiobutton(wt_row, text=label, variable=self._var_work_type, value=str(wt)).pack(
                side="left", padx=(0, 8)
            )

        # ── Overtime ──────────────────────────────────────────────────────────
        lf_ot = ttk.LabelFrame(inner, text="Overtime", padding=(8, 4, 8, 8))
        lf_ot.pack(fill="x", **pad)

        ot_row = ttk.Frame(lf_ot)
        ot_row.pack(fill="x")
        ttk.Label(ot_row, text="Rate multiplier:").pack(side="left")
        self._var_ot_rate = tk.StringVar(value=str(self._settings.get("overtime_rate") or 1.0))
        ttk.Spinbox(
            ot_row, textvariable=self._var_ot_rate,
            from_=0.5, to=5.0, increment=0.1, width=6, format="%.1f",
        ).pack(side="left", padx=(4, 16))
        ttk.Label(ot_row, text="Period:").pack(side="left")
        self._var_ot_period = tk.StringVar(value=self._settings.get("overtime_period") or "month")
        ttk.Combobox(
            ot_row, textvariable=self._var_ot_period,
            values=_OVERTIME_PERIODS, state="readonly", width=8,
        ).pack(side="left", padx=(4, 0))

        # ── Holiday Auto-Import ───────────────────────────────────────────────
        lf_hol = ttk.LabelFrame(inner, text="Holiday Auto-Import", padding=(8, 4, 8, 8))
        lf_hol.pack(fill="x", **pad)

        hol_row = ttk.Frame(lf_hol)
        hol_row.pack(fill="x")
        ttk.Label(hol_row, text="Country:").pack(side="left")
        self._var_country = tk.StringVar(
            value=self._settings.get("last_country_holiday") or "UnitedStates"
        )
        ttk.Combobox(
            hol_row, textvariable=self._var_country,
            values=_COUNTRIES, state="readonly", width=16,
        ).pack(side="left", padx=(4, 12))
        ttk.Label(hol_row, text="Year:").pack(side="left")
        cur_year = date.today().year
        self._var_hol_year = tk.StringVar(value=str(cur_year))
        ttk.Spinbox(
            hol_row, textvariable=self._var_hol_year,
            from_=cur_year - 2, to=cur_year + 2, increment=1, width=6,
        ).pack(side="left", padx=(4, 12))

        try:
            import holidays as _h  # noqa: F401
            hol_available = True
        except ImportError:
            hol_available = False

        self._btn_import_hol = ttk.Button(
            hol_row, text="Import Holidays for Year",
            command=self._import_holidays,
            state="normal" if hol_available else "disabled",
        )
        self._btn_import_hol.pack(side="left")

        if not hol_available:
            ttk.Label(lf_hol, text="Install 'holidays' package to enable", foreground="gray").pack(
                anchor="w", pady=(2, 0)
            )

        self._lbl_hol_status = ttk.Label(lf_hol, text="")
        self._lbl_hol_status.pack(anchor="w", pady=(4, 0))

    # ── Office helpers ────────────────────────────────────────────────────────

    def _get_offices(self) -> list[str]:
        return list(self._lb_offices.get(0, "end"))

    def _office_add(self) -> None:
        name = simpledialog.askstring("Add Office", "Office name:", parent=self)
        if name and name.strip():
            self._lb_offices.insert("end", name.strip())

    def _office_edit(self) -> None:
        sel = self._lb_offices.curselection()
        if not sel:
            messagebox.showwarning("Edit Office", "Select an office to edit.", parent=self)
            return
        idx = sel[0]
        old_name = self._lb_offices.get(idx)
        name = simpledialog.askstring("Edit Office", "Office name:", initialvalue=old_name, parent=self)
        if name and name.strip():
            self._lb_offices.delete(idx)
            self._lb_offices.insert(idx, name.strip())
            self._lb_offices.selection_set(idx)

    def _office_remove(self) -> None:
        sel = self._lb_offices.curselection()
        if not sel:
            messagebox.showwarning("Remove Office", "Select an office to remove.", parent=self)
            return
        self._lb_offices.delete(sel[0])

    # ── Holiday import ────────────────────────────────────────────────────────

    def _import_holidays(self) -> None:
        try:
            import holidays
        except ImportError:
            messagebox.showerror("Error", "The 'holidays' package is not installed.", parent=self)
            return

        country = self._var_country.get()
        try:
            year = int(self._var_hol_year.get())
        except ValueError:
            messagebox.showerror("Error", "Invalid year.", parent=self)
            return

        try:
            hol_dict = holidays.country_holidays(country, years=year)
        except Exception as exc:
            messagebox.showerror("Error", f"Could not load holidays for {country!r}: {exc}", parent=self)
            return

        existing = self._model_tc.get_date_exceptions()
        existing_dates = {exc["date"] for exc in existing}

        added = 0
        skipped = 0
        for h_date, h_name in sorted(hol_dict.items()):
            date_str = h_date.isoformat() if hasattr(h_date, "isoformat") else str(h_date)
            if date_str in existing_dates:
                skipped += 1
            else:
                self._model_tc.save_date_exception(date_str, 0.0, h_name)
                added += 1

        self._settings.set("last_country_holiday", country)
        self._lbl_hol_status.config(
            text=f"{added} added, {skipped} skipped (date already set)."
        )

    # ─────────────────────────── Tab 2: Date Exceptions ─────────────────────

    def _build_tab_exceptions(self, parent: ttk.Frame) -> None:
        outer = ttk.Frame(parent, padding=(12, 8, 12, 8))
        outer.pack(fill="both", expand=True)

        filter_row = ttk.Frame(outer)
        filter_row.pack(fill="x", pady=(0, 6))
        ttk.Label(filter_row, text="Year:").pack(side="left")
        cur_year = date.today().year
        exc_years = [str(y) for y in range(cur_year - 5, cur_year + 4)]
        self._exc_year_var = tk.StringVar(value=str(cur_year))
        cbo_exc_year = ttk.Combobox(
            filter_row, textvariable=self._exc_year_var,
            values=exc_years, state="readonly", width=8,
        )
        cbo_exc_year.pack(side="left", padx=(4, 0))
        cbo_exc_year.bind("<<ComboboxSelected>>", lambda e: self._exc_load())

        tree_frame = ttk.Frame(outer)
        tree_frame.pack(fill="both", expand=True, pady=(0, 6))

        cols = ("date", "hours", "label")
        self._exc_tree = ttk.Treeview(tree_frame, columns=cols, show="headings", height=12)
        self._exc_tree.heading("date", text="Date")
        self._exc_tree.heading("hours", text="Hours")
        self._exc_tree.heading("label", text="Label")
        self._exc_tree.column("date", width=120, stretch=False, anchor="w")
        self._exc_tree.column("hours", width=60, stretch=False, anchor="e")
        self._exc_tree.column("label", width=300, stretch=True, anchor="w")

        tree_vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self._exc_tree.yview)
        self._exc_tree.configure(yscrollcommand=tree_vsb.set)
        tree_vsb.pack(side="right", fill="y")
        self._exc_tree.pack(side="left", fill="both", expand=True)

        btn_row = ttk.Frame(outer)
        btn_row.pack(fill="x")
        ttk.Button(btn_row, text="Add", command=self._exc_add).pack(side="left", padx=(0, 4))
        ttk.Button(btn_row, text="Edit", command=self._exc_edit).pack(side="left", padx=(0, 4))
        ttk.Button(btn_row, text="Remove", command=self._exc_remove).pack(side="left")

        self._exc_load()

    def _exc_load(self) -> None:
        for item in self._exc_tree.get_children():
            self._exc_tree.delete(item)
        try:
            year = int(self._exc_year_var.get())
        except ValueError:
            return
        for exc in self._model_tc.get_date_exceptions(year):
            d = iso_to_date(exc["date"])
            self._exc_tree.insert(
                "", "end", iid=str(exc["id"]),
                values=(to_display_date(d), f"{exc['hours']:.1f}", exc["label"] or ""),
            )

    def _exc_add(self) -> None:
        _ExceptionDialog(self, self._model_tc, exc=None, on_saved=self._exc_load)

    def _exc_edit(self) -> None:
        sel = self._exc_tree.selection()
        if not sel:
            messagebox.showwarning("Edit", "Select an exception to edit.", parent=self)
            return
        exc_id = int(sel[0])
        try:
            year = int(self._exc_year_var.get())
        except ValueError:
            return
        exc = next((e for e in self._model_tc.get_date_exceptions(year) if e["id"] == exc_id), None)
        if exc is None:
            return
        _ExceptionDialog(self, self._model_tc, exc=exc, on_saved=self._exc_load)

    def _exc_remove(self) -> None:
        sel = self._exc_tree.selection()
        if not sel:
            messagebox.showwarning("Remove", "Select an exception to remove.", parent=self)
            return
        if messagebox.askyesno("Remove", "Remove this date exception?", parent=self):
            self._model_tc.delete_date_exception(int(sel[0]))
            self._exc_load()

    # ─────────────────────────── Tab 3: Vacation ─────────────────────────────

    def _build_tab_vacation(self, parent: ttk.Frame) -> None:
        outer = ttk.Frame(parent, padding=(16, 12, 16, 8))
        outer.pack(fill="both", expand=True)

        cur_year = date.today().year
        vac_years = [str(y) for y in range(cur_year - 3, cur_year + 4)]

        yr_row = ttk.Frame(outer)
        yr_row.pack(fill="x", pady=(0, 10))
        ttk.Label(yr_row, text="Year:", width=18, anchor="e").pack(side="left")
        self._vac_year_var = tk.StringVar(value=str(cur_year))
        cbo_vac = ttk.Combobox(yr_row, textvariable=self._vac_year_var, values=vac_years, state="readonly", width=8)
        cbo_vac.pack(side="left", padx=(4, 0))
        cbo_vac.bind("<<ComboboxSelected>>", lambda e: self._vac_load())

        hpy_row = ttk.Frame(outer)
        hpy_row.pack(fill="x", pady=(0, 6))
        ttk.Label(hpy_row, text="Hours per year:", width=18, anchor="e").pack(side="left")
        self._var_vac_hours = tk.StringVar(value="160.0")
        ttk.Spinbox(
            hpy_row, textvariable=self._var_vac_hours,
            from_=0.0, to=5000.0, increment=8.0, width=8, format="%.1f",
        ).pack(side="left", padx=(4, 0))

        mco_row = ttk.Frame(outer)
        mco_row.pack(fill="x", pady=(0, 6))
        ttk.Label(mco_row, text="Max carry-over:", width=18, anchor="e").pack(side="left")
        self._var_vac_carry = tk.StringVar(value="40.0")
        ttk.Spinbox(
            mco_row, textvariable=self._var_vac_carry,
            from_=0.0, to=5000.0, increment=8.0, width=8, format="%.1f",
        ).pack(side="left", padx=(4, 0))

        ttk.Button(outer, text="Save Vacation Settings", command=self._vac_save).pack(anchor="w", pady=(10, 0))

        self._lbl_vac_status = ttk.Label(outer, text="")
        self._lbl_vac_status.pack(anchor="w", pady=(4, 0))

        self._vac_load()

    def _vac_load(self) -> None:
        try:
            year = int(self._vac_year_var.get())
        except ValueError:
            return
        s = self._model_vacation.get_settings(year)
        if s:
            self._var_vac_hours.set(f"{s['hours_per_year']:.1f}")
            self._var_vac_carry.set(f"{s['max_carry_over']:.1f}")
        else:
            self._var_vac_hours.set("160.0")
            self._var_vac_carry.set("40.0")
        self._lbl_vac_status.config(text="")

    def _vac_save(self) -> None:
        try:
            year = int(self._vac_year_var.get())
            hours = float(self._var_vac_hours.get())
            carry = float(self._var_vac_carry.get())
        except ValueError:
            messagebox.showerror("Error", "Invalid values.", parent=self)
            return
        self._model_vacation.save_settings(year, hours, carry)
        self._lbl_vac_status.config(text=f"Saved vacation settings for {year}.")

    # ─────────────────────────── Tab 4: Sickness ─────────────────────────────

    def _build_tab_sickness(self, parent: ttk.Frame) -> None:
        outer = ttk.Frame(parent, padding=(16, 12, 16, 8))
        outer.pack(fill="both", expand=True)

        cur_year = date.today().year
        sick_years = [str(y) for y in range(cur_year - 3, cur_year + 4)]

        yr_row = ttk.Frame(outer)
        yr_row.pack(fill="x", pady=(0, 10))
        ttk.Label(yr_row, text="Year:", width=18, anchor="e").pack(side="left")
        self._sick_year_var = tk.StringVar(value=str(cur_year))
        cbo_sick = ttk.Combobox(yr_row, textvariable=self._sick_year_var, values=sick_years, state="readonly", width=8)
        cbo_sick.pack(side="left", padx=(4, 0))
        cbo_sick.bind("<<ComboboxSelected>>", lambda e: self._sick_load())

        dpy_row = ttk.Frame(outer)
        dpy_row.pack(fill="x", pady=(0, 6))
        ttk.Label(dpy_row, text="Days per year:", width=18, anchor="e").pack(side="left")
        self._var_sick_days = tk.StringVar(value="10.0")
        ttk.Spinbox(
            dpy_row, textvariable=self._var_sick_days,
            from_=0.0, to=365.0, increment=1.0, width=8, format="%.1f",
        ).pack(side="left", padx=(4, 0))

        ttk.Button(outer, text="Save Sickness Settings", command=self._sick_save).pack(anchor="w", pady=(10, 0))

        self._lbl_sick_status = ttk.Label(outer, text="")
        self._lbl_sick_status.pack(anchor="w", pady=(4, 0))

        self._sick_load()

    def _sick_load(self) -> None:
        try:
            year = int(self._sick_year_var.get())
        except ValueError:
            return
        days = self._model_sickness.get_settings(year)
        self._var_sick_days.set(f"{days:.1f}" if days is not None else "10.0")
        self._lbl_sick_status.config(text="")

    def _sick_save(self) -> None:
        try:
            year = int(self._sick_year_var.get())
            days = float(self._var_sick_days.get())
        except ValueError:
            messagebox.showerror("Error", "Invalid values.", parent=self)
            return
        self._model_sickness.save_settings(year, days)
        self._lbl_sick_status.config(text=f"Saved sickness settings for {year}.")

    # ─────────────────────────── Tab 5: Display ──────────────────────────────

    def _build_tab_display(self, parent: ttk.Frame) -> None:
        outer = ttk.Frame(parent, padding=(16, 12, 16, 8))
        outer.pack(fill="both", expand=True)

        hebrew_val = self._settings.get("show_hebrew_dates")
        self._var_hebrew = tk.BooleanVar(value=True if hebrew_val is None else bool(hebrew_val))
        ttk.Checkbutton(
            outer,
            text="Show Hebrew dates (requires 'hdate' package)",
            variable=self._var_hebrew,
        ).pack(anchor="w", pady=(0, 14))

        lf_theme = ttk.LabelFrame(outer, text="Theme", padding=(8, 4, 8, 8))
        lf_theme.pack(fill="x")
        self._var_theme = tk.StringVar(value=self._settings.get("theme") or "system")
        for val, label in [("light", "Light"), ("dark", "Dark"), ("system", "System")]:
            ttk.Radiobutton(lf_theme, text=label, variable=self._var_theme, value=val).pack(
                anchor="w", pady=2
            )

    # ─────────────────────────── Save ────────────────────────────────────────

    def _on_save(self) -> None:
        # Day targets — unchecked days stored as 0.0 (treated as no-target in balance)
        targets: dict[int, float] = {}
        for i, (chk_var, hrs_var) in enumerate(self._day_vars):
            if chk_var.get():
                try:
                    h = float(hrs_var.get())
                except ValueError:
                    h = 8.0
                targets[i] = max(0.0, h)
            else:
                targets[i] = 0.0
        self._model_tc.save_work_day_targets(targets)

        self._settings.set("offices", self._get_offices())

        presets: list[int] = []
        for v in self._break_vars:
            try:
                val = int(v.get())
                if val > 0:
                    presets.append(val)
            except ValueError:
                pass
        self._settings.set("break_presets", presets)

        self._settings.set("default_work_type", self._var_work_type.get())

        try:
            rate = float(self._var_ot_rate.get())
        except ValueError:
            rate = 1.0
        self._settings.set("overtime_rate", rate)
        self._settings.set("overtime_period", self._var_ot_period.get())

        self._settings.set("show_hebrew_dates", self._var_hebrew.get())
        self._settings.set("theme", self._var_theme.get())

        self._bus.publish(Event.SETTINGS_CHANGED)
        self.destroy()


# ─────────────────────────── Exception Add/Edit Dialog ───────────────────────

class _ExceptionDialog(tk.Toplevel):
    """Add / Edit a single date exception."""

    def __init__(
        self,
        parent,
        model_tc: TimeClockModel,
        exc: Optional[dict],
        on_saved: Callable,
    ) -> None:
        super().__init__(parent)
        self._model_tc = model_tc
        self._exc = exc
        self._on_saved = on_saved

        self.title("Edit Date Exception" if exc else "Add Date Exception")
        self.resizable(False, False)
        self.minsize(340, 220)
        self.transient(parent)
        self.grab_set()

        self._build_ui()
        if exc:
            self._populate(exc)

        self.wait_window(self)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=(16, 12, 16, 8))
        outer.pack(fill="both", expand=True)

        date_row = ttk.Frame(outer)
        date_row.pack(fill="x", pady=(0, 6))
        ttk.Label(date_row, text="Date:", width=10, anchor="e").pack(side="left")
        self._date_widget, self._get_date, self._set_date = make_date_picker(date_row)
        self._date_widget.pack(side="left", padx=(4, 0))

        hrs_row = ttk.Frame(outer)
        hrs_row.pack(fill="x", pady=(0, 6))
        ttk.Label(hrs_row, text="Hours:", width=10, anchor="e").pack(side="left")
        self._var_hours = tk.StringVar(value="0.0")
        ttk.Spinbox(
            hrs_row, textvariable=self._var_hours,
            from_=0.0, to=24.0, increment=0.5, width=6, format="%.1f",
        ).pack(side="left", padx=(4, 0))

        lbl_row = ttk.Frame(outer)
        lbl_row.pack(fill="x", pady=(0, 6))
        ttk.Label(lbl_row, text="Label:", width=10, anchor="e").pack(side="left")
        self._var_label = tk.StringVar()
        ttk.Entry(lbl_row, textvariable=self._var_label, width=26).pack(side="left", padx=(4, 0), fill="x", expand=True)

        self._lbl_error = ttk.Label(outer, text="", foreground="red", wraplength=300, justify="left")
        self._lbl_error.pack(fill="x", pady=(0, 4))

        btn_row = ttk.Frame(outer)
        btn_row.pack(fill="x", pady=(4, 0))
        ttk.Button(btn_row, text="Cancel", command=self.destroy).pack(side="right", padx=(6, 0))
        ttk.Button(btn_row, text="Save", command=self._on_save).pack(side="right")

    def _populate(self, exc: dict) -> None:
        self._set_date(iso_to_date(exc["date"]))
        self._var_hours.set(f"{exc['hours']:.1f}")
        self._var_label.set(exc["label"] or "")

    def _on_save(self) -> None:
        self._lbl_error.config(text="")
        try:
            d = self._get_date()
        except Exception:
            self._lbl_error.config(text="Invalid date.")
            return
        try:
            hours = float(self._var_hours.get())
        except ValueError:
            self._lbl_error.config(text="Hours must be a number.")
            return

        date_str = date_to_iso(d)
        label: Optional[str] = self._var_label.get().strip() or None

        if self._exc is not None:
            self._model_tc.delete_date_exception(self._exc["id"])
        self._model_tc.save_date_exception(date_str, hours, label)

        self._on_saved()
        self.destroy()
