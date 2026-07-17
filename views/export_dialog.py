"""Export dialog — exports Time, Vacation, or Sickness records to CSV, Excel, or PDF."""

from __future__ import annotations

import csv
import logging
import os
import tkinter as tk
from datetime import date
from tkinter import filedialog, messagebox, ttk

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from core.hebrew_date import to_hebrew_label as _safe_hebrew
from core.report import fetch_with_skip_count
from core.timeutil import MONTH_NAMES as _MONTH_NAMES
from core.timeutil import duration, to_display_date
from domain.enums import VacationType, WorkType, is_debit_vacation_type
from domain.types import SicknessRecord, TimeRecord, VacationRecord
from models.sickness_model import SicknessModel
from models.time_clock_model import TimeClockModel
from models.vacation_model import VacationModel
from views.date_picker import make_date_picker
from views.dialog_common import setup_modal_window
from views.enums import ExportFormat, ExportTab

logger = logging.getLogger(__name__)

# ── Label maps ───────────────────────────────────────────────────────────────


_VTYPE_LABELS: dict[VacationType, str] = {
    VacationType.ANNUAL_LEAVE: "Annual Leave",
    VacationType.PUBLIC_HOLIDAY: "Public Holiday",
    VacationType.SPECIAL_LEAVE: "Special Leave",
    VacationType.UNPAID_LEAVE: "Unpaid Leave",
    VacationType.CARRY_OVER: "Carry-Over",
}

_WTYPE_LABELS: dict[WorkType, str] = {
    WorkType.IN_SITE: "In Site",
    WorkType.ROAD: "Road",
    WorkType.REMOTE: "Remote",
}

_AnyRecord = TimeRecord | VacationRecord | SicknessRecord


class ExportDialog(tk.Toplevel):
    """Dialog for exporting Time, Vacation, or Sickness records to CSV, Excel,
    or PDF.
    """

    def __init__(
        self,
        parent,
        model_tc: TimeClockModel,
        model_vacation: VacationModel,
        model_sickness: SicknessModel,
        tab: ExportTab = ExportTab.TIME,
    ) -> None:
        super().__init__(parent)
        self._model_tc = model_tc
        self._model_vacation = model_vacation
        self._model_sickness = model_sickness

        setup_modal_window(self, parent, "Export Records", minsize=(400, 320))

        today = date.today()
        self._default_from = date(today.year, 1, 1)
        self._default_to = today

        self._var_data = tk.StringVar(value=str(tab))
        self._var_fmt = tk.StringVar(value=str(ExportFormat.CSV))
        self._var_group = tk.BooleanVar(value=True)

        self._build_ui()
        self.wait_window(self)

    # ─────────────────────────── UI Construction ────────────────────────────

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=(16, 12, 16, 8))
        outer.pack(fill="both", expand=True)

        # ── Data radio buttons ────────────────────────────────────────────────
        data_frame = ttk.Frame(outer)
        data_frame.pack(fill="x", pady=(0, 8))
        ttk.Label(data_frame, text="Data:", width=10, anchor="w").pack(side="left")
        for value, label in (
            (ExportTab.TIME, "Time Records"),
            (ExportTab.VACATION, "Vacation"),
            (ExportTab.SICKNESS, "Sickness"),
        ):
            ttk.Radiobutton(
                data_frame, text=label, variable=self._var_data, value=str(value)
            ).pack(side="left", padx=(0, 8))

        # ── Date range ───────────────────────────────────────────────────────
        date_frame = ttk.Frame(outer)
        date_frame.pack(fill="x", pady=(0, 8))

        ttk.Label(date_frame, text="From:", width=10, anchor="w").pack(side="left")
        self._dp_from, self._get_from, self._set_from = make_date_picker(date_frame)
        self._dp_from.pack(side="left", padx=(0, 12))
        self._set_from(self._default_from)

        ttk.Label(date_frame, text="To:").pack(side="left", padx=(0, 4))
        self._dp_to, self._get_to, self._set_to = make_date_picker(date_frame)
        self._dp_to.pack(side="left")
        self._set_to(self._default_to)

        # ── Format radio buttons ─────────────────────────────────────────────
        fmt_frame = ttk.Frame(outer)
        fmt_frame.pack(fill="x", pady=(0, 8))
        ttk.Label(fmt_frame, text="Format:", width=10, anchor="w").pack(side="left")

        ttk.Radiobutton(
            fmt_frame, text="CSV", variable=self._var_fmt, value=str(ExportFormat.CSV)
        ).pack(side="left", padx=(0, 8))

        ttk.Radiobutton(
            fmt_frame,
            text="Excel",
            variable=self._var_fmt,
            value=str(ExportFormat.EXCEL),
        ).pack(side="left", padx=(0, 8))

        ttk.Radiobutton(
            fmt_frame, text="PDF", variable=self._var_fmt, value=str(ExportFormat.PDF)
        ).pack(side="left")

        # ── Options ──────────────────────────────────────────────────────────
        opts_frame = ttk.LabelFrame(outer, text="Options", padding=(8, 4))
        opts_frame.pack(fill="x", pady=(0, 8))

        ttk.Checkbutton(
            opts_frame, text="Group by month", variable=self._var_group
        ).pack(anchor="w")

        # ── Buttons ──────────────────────────────────────────────────────────
        btn_row = ttk.Frame(outer)
        btn_row.pack(fill="x", pady=(8, 0))
        ttk.Button(btn_row, text="Cancel", command=self.destroy).pack(
            side="right", padx=(6, 0)
        )
        ttk.Button(
            btn_row, text="Export", style="Accent.TButton", command=self._on_export
        ).pack(side="right")

    # ─────────────────────────── Export Action ───────────────────────────────

    def _on_export(self) -> None:
        try:
            from_date = self._get_from()
            to_date = self._get_to()
        except Exception as exc:  # pylint: disable=broad-exception-caught
            # date-entry widgets (tkcalendar/manual parsing) can raise
            # ValueError, tkinter errors, etc.; surfaced to the user below.
            logger.warning("Could not read export date range", exc_info=True)
            messagebox.showerror(
                "Invalid Date", f"Could not read date: {exc}", parent=self
            )
            return

        if from_date > to_date:
            messagebox.showerror(
                "Invalid Date Range",
                "The 'From' date must not be after the 'To' date.",
                parent=self,
            )
            return

        records, skipped_count = self._fetch_records(from_date, to_date)

        fmt = ExportFormat(self._var_fmt.get())
        filetypes, default_ext = self._file_dialog_params(fmt)

        path = filedialog.asksaveasfilename(
            parent=self,
            title="Export Records",
            defaultextension=default_ext,
            filetypes=filetypes,
        )
        if not path:
            return

        # Write to a temp file next to the final path and rename into place
        # only on success, so a mid-export failure can never leave a
        # truncated/partial file at `path` that could be mistaken for a
        # complete payroll/hours record.
        tmp_path = path + ".tmp"
        try:
            if fmt == ExportFormat.CSV:
                self._export_csv(records, tmp_path)
            elif fmt == ExportFormat.EXCEL:
                self._export_excel(records, tmp_path)
            elif fmt == ExportFormat.PDF:
                self._export_pdf(records, tmp_path)
            else:
                raise ValueError(f"Unknown format: {fmt!r}")
            os.replace(tmp_path, path)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            # export libraries (pandas/reportlab) and file I/O can raise many
            # different error types (disk full, permission denied, malformed
            # data); logged and surfaced to the user below.
            logger.exception("Export failed for format=%s path=%s", fmt, path)
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    logger.warning(
                        "Could not remove partial export temp file %s", tmp_path
                    )
            messagebox.showerror("Export Failed", str(exc), parent=self)
            return

        if skipped_count > 0:
            messagebox.showwarning(
                "Export Complete (With Warnings)",
                f"Records exported to:\n{path}\n\n"
                f"{skipped_count} record(s) skipped due to data errors.",
                parent=self,
            )
        else:
            messagebox.showinfo(
                "Export Complete", f"Records exported to:\n{path}", parent=self
            )
        self.destroy()

    # ─────────────────────────── Data Fetching ───────────────────────────────

    def _fetch_records(
        self, from_date: date, to_date: date
    ) -> tuple[list[_AnyRecord], int]:
        """Query the selected model for all records that fall within the date
        range.

        Returns `(records, skipped_count)`, where `skipped_count` is the
        total number of malformed DB rows silently dropped by the
        underlying model(s) while fetching -- see
        models/_row_mapping.py:rows_to_records() and each model's
        `last_skipped_count` attribute. Each per-year fetch is routed through
        core.report.fetch_with_skip_count(), which reads that model's
        `last_skipped_count` immediately adjacent to the fetch and returns an
        explicit `(records, skipped)` tuple; the count is then accumulated by
        value, so no later fetch (this iteration's or the next year's) can
        detach it from the fetch it describes. This is the more important of
        the two report/export call sites to get right: the temp-file/rename
        dance in `_on_export()` exists so a partial export can never be
        mistaken for a complete payroll/hours record, and a silently-dropped
        row here would produce exactly that failure mode without this count
        being surfaced to the caller.
        """
        tab = ExportTab(self._var_data.get())
        all_records: list[_AnyRecord] = []
        skipped_count = 0

        for year in range(from_date.year, to_date.year + 1):
            # Initialized before the branch so the `skipped_count +=` below is
            # never reached with year_skipped unbound -- guards against a future
            # ExportTab member that no branch here assigns.
            year_skipped = 0
            if tab == ExportTab.TIME:
                tc_records, year_skipped = fetch_with_skip_count(
                    self._model_tc,
                    lambda year=year: self._model_tc.get_records_for_period(year),
                )
                all_records.extend(tc_records)
            elif tab == ExportTab.VACATION:
                vac_records, year_skipped = fetch_with_skip_count(
                    self._model_vacation,
                    lambda year=year: self._model_vacation.get_records_for_year(year),
                )
                all_records.extend(vac_records)
            else:  # sickness
                sick_records, year_skipped = fetch_with_skip_count(
                    self._model_sickness,
                    lambda year=year: self._model_sickness.get_records_for_year(year),
                )
                all_records.extend(sick_records)
            skipped_count += year_skipped

        filtered = [r for r in all_records if from_date <= r.date <= to_date]
        filtered.sort(key=lambda r: r.date)
        return filtered, skipped_count

    # ─────────────────────────── Column / Row Helpers ────────────────────────

    def _columns(self, tab: ExportTab) -> list[str]:
        """Return ordered column header list for the given data type."""
        if tab == ExportTab.TIME:
            cols = [
                "Date",
                "Hebrew Date",
                "Start",
                "End",
                "Break (min)",
                "Type",
                "Office",
                "Note",
                "Net Hours",
            ]
        elif tab == ExportTab.VACATION:
            cols = ["Date", "Hebrew Date", "Hours", "Charged Hours", "Type", "Note"]
        else:  # sickness
            cols = ["Date", "Hebrew Date", "Hours", "Note"]
        return cols

    def _record_to_values(self, rec: _AnyRecord, tab: ExportTab) -> list:
        """Convert a single record to a flat list of cell values (strings / numbers)."""
        hebrew = _safe_hebrew(rec.date)
        if tab == ExportTab.TIME:
            if not isinstance(rec, TimeRecord):
                raise TypeError(f"Expected TimeRecord, got {type(rec).__name__}")
            net: str = (
                f"{duration(rec.start_time, rec.end_time, rec.break_minutes):.2f}"
                if rec.end_time
                else ""
            )
            return [
                to_display_date(rec.date),
                hebrew,
                rec.start_time.strftime("%H:%M"),
                rec.end_time.strftime("%H:%M") if rec.end_time else "",
                rec.break_minutes,
                _WTYPE_LABELS.get(rec.work_type, str(rec.work_type)),
                rec.office or "",
                rec.note or "",
                net,
            ]
        if tab == ExportTab.VACATION:
            if not isinstance(rec, VacationRecord):
                raise TypeError(f"Expected VacationRecord, got {type(rec).__name__}")
            # Carry-over and unpaid leave don't debit the pool, so they charge
            # zero hours regardless of charge_rate (see is_debit_vacation_type).
            charged = (
                round(rec.hours * rec.charge_rate, 2)
                if is_debit_vacation_type(rec.vtype)
                else 0
            )
            return [
                to_display_date(rec.date),
                hebrew,
                rec.hours,
                charged,
                _VTYPE_LABELS.get(rec.vtype, str(rec.vtype)),
                rec.note or "",
            ]
        # sickness
        if not isinstance(rec, SicknessRecord):
            raise TypeError(f"Expected SicknessRecord, got {type(rec).__name__}")
        return [
            to_display_date(rec.date),
            hebrew,
            rec.hours,
            rec.note or "",
        ]

    def _compute_total(self, records: list[_AnyRecord], tab: ExportTab) -> float:
        """Return total net hours (time) or total hours (vacation/sickness)."""
        total = 0.0
        for rec in records:
            if tab == ExportTab.TIME:
                if not isinstance(rec, TimeRecord):
                    raise TypeError(f"Expected TimeRecord, got {type(rec).__name__}")
                if rec.end_time:
                    total += duration(rec.start_time, rec.end_time, rec.break_minutes)
            else:
                if not isinstance(rec, (VacationRecord, SicknessRecord)):
                    raise TypeError(
                        "Expected VacationRecord or SicknessRecord, got "
                        f"{type(rec).__name__}"
                    )
                total += rec.hours
        return total

    def _vacation_summary_extras(
        self, records: list[_AnyRecord]
    ) -> tuple[float, float]:
        """Return (extra_grant, borrowed) hours summed across every distinct
        year present in `records`.

        Both figures are year-level (a vacation summary is computed per year),
        so a multi-year export sums each year's ad-hoc grant total and the
        hours the previous year borrowed forward (``borrowed_prev``).
        """
        extra_grant = 0.0
        borrowed = 0.0
        for year in sorted({rec.date.year for rec in records}):
            summary = self._model_vacation.calculate_vacation_summary(year)
            extra_grant += summary.extra_grant
            borrowed += summary.borrowed_prev
        return extra_grant, borrowed

    def _vacation_summary_rows(self, records: list[_AnyRecord]) -> list[list]:
        """Build the vacation summary block: raw + charged hour totals, plus
        extra-grant and borrowed lines, aligned to the vacation column layout.
        """
        columns = self._columns(ExportTab.VACATION)
        vac_records = [r for r in records if isinstance(r, VacationRecord)]
        raw_total = sum((r.hours for r in vac_records), 0.0)
        charged_total = sum(
            (
                r.hours * r.charge_rate
                for r in vac_records
                if is_debit_vacation_type(r.vtype)
            ),
            0.0,
        )
        extra_grant, borrowed = self._vacation_summary_extras(records)

        def _row(
            label: str, hours_val: float, charged_val: float | None = None
        ) -> list:
            row: list = [""] * len(columns)
            row[0] = label
            row[2] = f"{hours_val:.1f}h"  # "Hours" column
            if charged_val is not None:
                row[3] = f"{charged_val:.1f}h"  # "Charged Hours" column
            return row

        return [
            _row("Total", raw_total, charged_total),
            _row("Extra Grant", extra_grant),
            _row("Borrowed (prev yr)", borrowed),
        ]

    @staticmethod
    def _file_dialog_params(fmt: ExportFormat) -> tuple[list[tuple[str, str]], str]:
        if fmt == ExportFormat.EXCEL:
            return [("Excel files", "*.xlsx"), ("All files", "*.*")], ".xlsx"
        if fmt == ExportFormat.PDF:
            return [("PDF files", "*.pdf"), ("All files", "*.*")], ".pdf"
        return [("CSV files", "*.csv"), ("All files", "*.*")], ".csv"

    # ─────────────────────────── CSV Export ─────────────────────────────────

    def _export_csv(self, records: list[_AnyRecord], path: str) -> None:
        tab = ExportTab(self._var_data.get())
        group_by_month = bool(self._var_group.get())

        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(self._columns(tab))

            current_month: tuple[int, int] | None = None
            for rec in records:
                if group_by_month:
                    month_key = (rec.date.year, rec.date.month)
                    if current_month is not None and month_key != current_month:
                        writer.writerow([])  # blank separator between months
                    current_month = month_key

                writer.writerow(self._record_to_values(rec, tab))

            if tab == ExportTab.VACATION:
                writer.writerow([])  # blank separator before the summary block
                for summary_row in self._vacation_summary_rows(records):
                    writer.writerow(summary_row)

    # ─────────────────────────── Excel Export ───────────────────────────────

    def _export_excel(self, records: list[_AnyRecord], path: str) -> None:

        tab = ExportTab(self._var_data.get())
        columns = self._columns(tab)
        rows = [self._record_to_values(rec, tab) for rec in records]

        df = pd.DataFrame(rows, columns=columns)
        df.to_excel(path, index=False, sheet_name="Records", engine="openpyxl")

    # ─────────────────────────── PDF Export ─────────────────────────────────

    def _export_pdf(self, records: list[_AnyRecord], path: str) -> None:

        tab = ExportTab(self._var_data.get())
        group_by_month = bool(self._var_group.get())
        columns = self._columns(tab)

        # Time records have more columns — use landscape
        page_size = landscape(A4) if tab == ExportTab.TIME else A4

        doc = SimpleDocTemplate(
            path,
            pagesize=page_size,
            topMargin=1.5 * cm,
            bottomMargin=1.5 * cm,
            leftMargin=1.5 * cm,
            rightMargin=1.5 * cm,
        )

        styles = getSampleStyleSheet()
        flowables = []

        title_text = {
            ExportTab.TIME: "Time Records",
            ExportTab.VACATION: "Vacation Records",
            ExportTab.SICKNESS: "Sickness Records",
        }.get(tab, "Records")
        flowables.append(Paragraph(title_text, styles["Heading1"]))
        flowables.append(Spacer(1, 0.4 * cm))

        # ── Build table rows ─────────────────────────────────────────────────
        table_data: list[list] = [columns]
        month_header_rows: set[int] = set()

        current_month: tuple[int, int] | None = None

        for rec in records:
            if group_by_month:
                month_key = (rec.date.year, rec.date.month)
                if month_key != current_month:
                    current_month = month_key
                    month_label = f"{_MONTH_NAMES[month_key[1]]} {month_key[0]}"
                    month_row = [month_label] + [""] * (len(columns) - 1)
                    month_header_rows.add(len(table_data))
                    table_data.append(month_row)

            table_data.append(self._record_to_values(rec, tab))

        # ── Summary rows ─────────────────────────────────────────────────────
        # Vacation gets a multi-line block (raw + charged totals, extra grant,
        # borrowed); time/sickness keep the single "Total: Xh" row.  Only the
        # single-total tabs need `total`, so it is computed there rather than
        # accumulated in the shared loop above (vacation would discard it).
        if tab == ExportTab.VACATION:
            summary_rows = self._vacation_summary_rows(records)
        else:
            decimals = 2 if tab == ExportTab.TIME else 1
            total = self._compute_total(records, tab)
            total_row: list = [""] * len(columns)
            total_row[0] = f"Total: {total:.{decimals}f}h"
            summary_rows = [total_row]

        summary_start_idx = len(table_data)
        table_data.extend(summary_rows)
        summary_row_indices = set(range(summary_start_idx, len(table_data)))

        # ── Table style ──────────────────────────────────────────────────────
        style_cmds: list = [
            # Header row
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#555555")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            # Data rows
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 1), (-1, -1), 8),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            # Grid
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ]

        # Summary rows (total, plus vacation extra-grant/borrowed lines)
        for idx in summary_row_indices:
            style_cmds += [
                ("FONTNAME", (0, idx), (-1, idx), "Helvetica-Bold"),
                ("BACKGROUND", (0, idx), (-1, idx), colors.HexColor("#e0e0e0")),
            ]

        # Alternating row backgrounds for data rows
        for i in range(1, len(table_data)):
            if i in month_header_rows or i in summary_row_indices:
                continue
            bg = colors.white if i % 2 == 1 else colors.HexColor("#f5f5f5")
            style_cmds.append(("BACKGROUND", (0, i), (-1, i), bg))

        # Month header row styling
        for row_idx in month_header_rows:
            style_cmds += [
                ("BACKGROUND", (0, row_idx), (-1, row_idx), colors.HexColor("#4682b4")),
                ("TEXTCOLOR", (0, row_idx), (-1, row_idx), colors.white),
                ("FONTNAME", (0, row_idx), (-1, row_idx), "Helvetica-Bold"),
                ("FONTSIZE", (0, row_idx), (-1, row_idx), 9),
                ("SPAN", (0, row_idx), (-1, row_idx)),
            ]

        table = Table(table_data, repeatRows=1)
        table.setStyle(TableStyle(style_cmds))
        flowables.append(table)

        doc.build(flowables)
