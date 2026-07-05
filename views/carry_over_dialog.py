"""Carry-Over Allocation dialog — transfer unused vacation hours to the next year."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from controllers.vacation_controller import VacationController
from models.vacation_model import VacationModel
from views.dialog_common import setup_modal_window


class CarryOverDialog(tk.Toplevel):
    """Dialog for allocating carry-over hours from the previous year."""

    def __init__(
        self,
        parent,
        controller: VacationController,
        model: VacationModel,
        to_year: int,
        **_kwargs,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._model = model
        self._to_year = to_year
        self._from_year = to_year - 1

        setup_modal_window(
            self, parent, f"Add Carry-Over to {to_year}", minsize=(360, 200)
        )

        self._allowance = self._model.calculate_carry_over_allowance(to_year)
        self._build_ui()

        self.wait_window(self)

    # ─────────────────────────── UI Construction ────────────────────────────

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=(16, 12, 16, 8))
        outer.pack(fill="both", expand=True)

        a = self._allowance
        prev_surplus = a.prev_surplus
        max_carry_over = a.max_carry_over
        already_transferred = a.already_transferred
        allowed = a.allowed_transfer

        # ── Info rows ─────────────────────────────────────────────────────────
        info_frame = ttk.Frame(outer)
        info_frame.pack(fill="x", pady=(0, 10))

        def _info_row(label: str, value: str) -> None:
            row = ttk.Frame(info_frame)
            row.pack(fill="x", pady=1)
            ttk.Label(row, text=label, width=32, anchor="w").pack(side="left")
            ttk.Label(row, text=value, anchor="e").pack(side="left")

        _info_row(
            f"Previous year ({self._from_year}) unused:",
            f"{prev_surplus:.1f}h",
        )
        _info_row("Max carry-over allowed:", f"{max_carry_over:.1f}h")
        _info_row(
            f"Already transferred to {self._to_year}:",
            f"{already_transferred:.1f}h",
        )

        ttk.Separator(outer, orient="horizontal").pack(fill="x", pady=(0, 8))

        # ── Hours input ───────────────────────────────────────────────────────
        input_row = ttk.Frame(outer)
        input_row.pack(fill="x", pady=(0, 6))
        ttk.Label(
            input_row, text=f"Add to {self._to_year}:", width=18, anchor="e"
        ).pack(side="left")
        self._var_hours = tk.StringVar(value=f"{allowed:.1f}")
        self._spn_hours = ttk.Spinbox(
            input_row,
            textvariable=self._var_hours,
            from_=0.0,
            to=max(allowed, 0.0),
            increment=0.5,
            width=8,
            format="%.1f",
        )
        self._spn_hours.pack(side="left", padx=(4, 6))
        ttk.Label(
            input_row,
            text=f"(max {allowed:.1f}h)",
            foreground="gray",
        ).pack(side="left")

        # ── Error label ───────────────────────────────────────────────────────
        self._lbl_error = ttk.Label(
            outer, text="", foreground="red", wraplength=328, justify="left"
        )
        self._lbl_error.pack(fill="x", pady=(0, 4))

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_row = ttk.Frame(outer)
        btn_row.pack(fill="x", pady=(4, 0))
        ttk.Button(btn_row, text="Cancel", command=self.destroy).pack(
            side="right", padx=(6, 0)
        )
        ttk.Button(
            btn_row, text="Add", style="Accent.TButton", command=self._on_add
        ).pack(side="right")

    # ─────────────────────────── Actions ────────────────────────────────────

    def _on_add(self) -> None:
        self._lbl_error.config(text="")
        try:
            hours = float(self._var_hours.get())
        except ValueError:
            self._lbl_error.config(text="Please enter a valid number of hours.")
            return

        allowed = self._allowance.allowed_transfer
        if hours <= 0:
            self._lbl_error.config(text="Hours must be greater than zero.")
            return
        if hours > allowed:
            self._lbl_error.config(
                text=f"Cannot transfer {hours:.1f}h. Maximum allowed is {allowed:.1f}h."
            )
            return

        result = self._controller.add_carry_over(self._from_year, self._to_year, hours)
        if result.ok:
            self.destroy()
        else:
            self._lbl_error.config(text="\n".join(result.errors))
