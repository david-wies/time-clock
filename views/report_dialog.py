"""Report generation dialog — preview and PDF export for Time Clock reports."""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import tkinter as tk
from datetime import date
from pathlib import Path
from tkinter import messagebox, ttk
from tkinter.filedialog import asksaveasfilename

from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus import (
    Image as RLImage,
)

from core.report import MONTH_NAMES, ReportData, period_range, period_summary
from core.timeutil import to_display_date
from domain.enums import PeriodType
from models.miliuim_model import MiliuimModel
from models.sickness_model import SicknessModel
from models.time_clock_model import TimeClockModel
from models.vacation_model import VacationModel
from settings import SettingsManager
from views.dialog_common import setup_modal_window

logger = logging.getLogger(__name__)

_QUARTER_VALUES = ["Q1", "Q2", "Q3", "Q4"]


def _fmt_h(hours: float) -> str:
    return f"{hours:.2f} h"


def _signed(value: float, decimals: int = 2) -> str:
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.{decimals}f}"


class ReportDialog(tk.Toplevel):
    """Modal dialog for generating monthly, quarterly, or yearly Time Clock reports."""

    def __init__(
        self,
        parent,
        model_tc: TimeClockModel,
        model_vacation: VacationModel,
        model_sickness: SicknessModel,
        settings: SettingsManager,
        model_miliuim: MiliuimModel | None = None,
    ) -> None:
        super().__init__(parent)
        self._model_tc = model_tc
        self._model_vacation = model_vacation
        self._model_sickness = model_sickness
        self._settings = settings
        self._model_miliuim = model_miliuim

        # Widgets/vars assigned in _build_ui() and its helpers; declared here
        # (bare annotations, no value) so their real first assignment isn't
        # flagged as attribute-defined-outside-init.
        self._var_period: tk.StringVar
        self._var_year: tk.StringVar
        self._spn_year: ttk.Spinbox
        self._lbl_month: ttk.Label
        self._var_month: tk.StringVar
        self._cbo_month: ttk.Combobox
        self._lbl_quarter: ttk.Label
        self._var_quarter: tk.StringVar
        self._cbo_quarter: ttk.Combobox
        self._txt_preview: tk.Text

        setup_modal_window(
            self, parent, "Generate Report", minsize=(480, 400), resizable=(True, True)
        )

        self._build_ui()
        self._on_period_changed()  # set initial visibility

        self.wait_window(self)

    # ─────────────────────────── UI Construction ────────────────────────────

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=(16, 12, 16, 12))
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(3, weight=1)  # preview text expands

        self._build_form(outer)

        ttk.Separator(outer, orient="horizontal").grid(
            row=1, column=0, sticky="ew", pady=(8, 6)
        )

        self._build_preview_area(outer)
        self._build_button_bar(outer)

    def _build_form(self, parent: ttk.Frame) -> None:
        frm = ttk.Frame(parent)
        frm.grid(row=0, column=0, sticky="ew")
        frm.columnconfigure(1, weight=1)

        cur_year = date.today().year

        # Period radio buttons
        ttk.Label(frm, text="Period:").grid(
            row=0, column=0, sticky="w", padx=(0, 8), pady=3
        )
        frm_radios = ttk.Frame(frm)
        frm_radios.grid(row=0, column=1, sticky="w", pady=3)
        self._var_period = tk.StringVar(value=str(PeriodType.MONTH))
        for label, value in [
            ("Month", PeriodType.MONTH),
            ("Quarter", PeriodType.QUARTER),
            ("Year", PeriodType.YEAR),
        ]:
            ttk.Radiobutton(
                frm_radios,
                text=label,
                variable=self._var_period,
                value=str(value),
                command=self._on_period_changed,
            ).pack(side="left", padx=(0, 10))

        # Year spinbox
        ttk.Label(frm, text="Year:").grid(
            row=1, column=0, sticky="w", padx=(0, 8), pady=3
        )
        self._var_year = tk.StringVar(value=str(cur_year))
        self._spn_year = ttk.Spinbox(
            frm,
            textvariable=self._var_year,
            from_=cur_year - 5,
            to=cur_year + 5,
            increment=1,
            width=8,
        )
        self._spn_year.grid(row=1, column=1, sticky="w", pady=3)

        # Month combobox (shown only for Month mode)
        self._lbl_month = ttk.Label(frm, text="Month:")
        self._lbl_month.grid(row=2, column=0, sticky="w", padx=(0, 8), pady=3)
        today = date.today()
        self._var_month = tk.StringVar(value=MONTH_NAMES[today.month])
        self._cbo_month = ttk.Combobox(
            frm,
            textvariable=self._var_month,
            values=MONTH_NAMES[1:],
            state="readonly",
            width=12,
        )
        self._cbo_month.grid(row=2, column=1, sticky="w", pady=3)

        # Quarter combobox (shown only for Quarter mode)
        self._lbl_quarter = ttk.Label(frm, text="Quarter:")
        self._lbl_quarter.grid(row=3, column=0, sticky="w", padx=(0, 8), pady=3)
        self._var_quarter = tk.StringVar(value="Q1")
        self._cbo_quarter = ttk.Combobox(
            frm,
            textvariable=self._var_quarter,
            values=_QUARTER_VALUES,
            state="readonly",
            width=8,
        )
        self._cbo_quarter.grid(row=3, column=1, sticky="w", pady=3)

    def _build_preview_area(self, parent: ttk.Frame) -> None:
        btn_row = ttk.Frame(parent)
        btn_row.grid(row=2, column=0, sticky="ew", pady=(0, 6))

        ttk.Button(btn_row, text="Preview Summary", command=self._do_preview).pack(
            side="left"
        )

        frm_txt = ttk.Frame(parent, relief="sunken", borderwidth=1)
        frm_txt.grid(row=3, column=0, sticky="nsew", pady=(0, 8))
        frm_txt.columnconfigure(0, weight=1)
        frm_txt.rowconfigure(0, weight=1)

        self._txt_preview = tk.Text(
            frm_txt,
            state="disabled",
            wrap="none",
            font=("Courier", 10),
            height=12,
            relief="flat",
            padx=6,
            pady=4,
        )
        self._txt_preview.grid(row=0, column=0, sticky="nsew")

        vsb = ttk.Scrollbar(frm_txt, orient="vertical", command=self._txt_preview.yview)
        vsb.grid(row=0, column=1, sticky="ns")
        self._txt_preview.configure(yscrollcommand=vsb.set)

        hsb = ttk.Scrollbar(
            frm_txt, orient="horizontal", command=self._txt_preview.xview
        )
        hsb.grid(row=1, column=0, sticky="ew")
        self._txt_preview.configure(xscrollcommand=hsb.set)

    def _build_button_bar(self, parent: ttk.Frame) -> None:
        ttk.Separator(parent, orient="horizontal").grid(
            row=4, column=0, sticky="ew", pady=(0, 8)
        )

        button_bar = ttk.Frame(parent)
        button_bar.grid(row=5, column=0, sticky="ew")

        ttk.Button(button_bar, text="Export PDF", command=self._do_export_pdf).pack(
            side="right", padx=(6, 0)
        )
        ttk.Button(button_bar, text="Cancel", command=self.destroy).pack(side="right")

    # ─────────────────────────── Period Toggle ───────────────────────────────

    def _on_period_changed(self) -> None:
        period = PeriodType(self._var_period.get())
        if period == PeriodType.MONTH:
            self._lbl_month.grid()
            self._cbo_month.grid()
            self._lbl_quarter.grid_remove()
            self._cbo_quarter.grid_remove()
        elif period == PeriodType.QUARTER:
            self._lbl_month.grid_remove()
            self._cbo_month.grid_remove()
            self._lbl_quarter.grid()
            self._cbo_quarter.grid()
        else:  # year
            self._lbl_month.grid_remove()
            self._cbo_month.grid_remove()
            self._lbl_quarter.grid_remove()
            self._cbo_quarter.grid_remove()

    # ─────────────────────────── Data Assembly ───────────────────────────────

    def _get_report_data(self) -> ReportData | None:
        try:
            year = int(self._var_year.get())
        except ValueError:
            messagebox.showerror(
                "Invalid Input", "Please enter a valid year.", parent=self
            )
            return None

        period_type = PeriodType(self._var_period.get())
        month: int | None = None
        quarter: int | None = None

        if period_type == PeriodType.MONTH:
            month_name = self._var_month.get()
            if month_name not in MONTH_NAMES[1:]:
                messagebox.showerror(
                    "Invalid Input", "Please select a valid month.", parent=self
                )
                return None
            month = MONTH_NAMES.index(month_name)

        elif period_type == PeriodType.QUARTER:
            q_str = self._var_quarter.get()
            try:
                quarter = int(q_str[1])
            except (IndexError, ValueError):
                messagebox.showerror(
                    "Invalid Input", "Please select a valid quarter.", parent=self
                )
                return None

        try:
            return period_summary(
                period_type=period_type,
                year=year,
                month=month,
                quarter=quarter,
                model_tc=self._model_tc,
                model_vacation=self._model_vacation,
                model_sickness=self._model_sickness,
                model_miliuim=self._model_miliuim,
                settings=self._settings,
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            # period_summary() delegates to multiple model/report layers that can
            # raise a variety of exception types; report to the user and log.
            logger.exception(
                "Failed to assemble report data for period_type=%s year=%s "
                "month=%s quarter=%s",
                period_type,
                year,
                month,
                quarter,
            )
            messagebox.showerror(
                "Report Error", f"Failed to assemble report data:\n{exc}", parent=self
            )
            return None

    # ─────────────────────────── Preview ────────────────────────────────────

    def _do_preview(self) -> None:
        data = self._get_report_data()
        if data is None:
            return
        text = self._build_preview_text(data)
        self._txt_preview.config(state="normal")
        self._txt_preview.delete("1.0", "end")
        self._txt_preview.insert("1.0", text)
        self._txt_preview.config(state="disabled")

    def _build_preview_text(self, data: ReportData) -> str:
        sep = "─" * 44
        lines: list[str] = []

        lines.append(f"Period: {data.period_label}")
        lines.append(sep)
        lines.append("")

        lines.append("TIME CLOCK")
        lines.append(f"  Worked:              {data.worked_hours:>9.2f} h")
        lines.append(f"  Target:              {data.target_hours:>9.2f} h")
        lines.append(f"  Balance:             {_signed(data.time_balance):>9} h")
        lines.append(
            f"  Weighted overtime:   {data.weighted_overtime:>9.2f} h"
            f"  (rate: {data.overtime_rate}x)"
        )
        lines.append("")

        lines.append(f"VACATION ({data.year})")
        lines.append(f"  Allowance:           {data.vac_allowance:>9.1f} h")
        lines.append(f"  Carry-over:          {data.vac_carry_over:>9.1f} h")
        lines.append(f"  Total pool:          {data.vac_total_pool:>9.1f} h")
        lines.append(f"  Used:                {data.vac_used:>9.1f} h")
        lines.append(f"  Remaining:           {data.vac_remaining:>9.1f} h")
        lines.append("")

        lines.append(f"SICKNESS ({data.year})")
        lines.append(f"  Allowance:           {data.sick_allowance_hours:>9.1f} h")
        lines.append(f"  Used:                {data.sick_used_hours:>9.1f} h")
        lines.append(f"  Remaining:           {data.sick_remaining_hours:>9.1f} h")
        lines.append("")

        lines.append(f"MILIUIM ({data.year})")
        lines.append(f"  Periods:             {data.miliuim_period_count:>9}")
        lines.append(f"  Total days:          {data.miliuim_total_days:>9}")

        if data.monthly_rows:
            lines.append("")
            lines.append("MONTHLY BREAKDOWN")
            lines.append(
                f"  {'Month':<16} {'Worked':>9}  {'Target':>9}  {'Balance':>10}"
            )
            lines.append(f"  {'-' * 16} {'-' * 9}  {'-' * 9}  {'-' * 10}")
            for row in data.monthly_rows:
                name = MONTH_NAMES[row.month]
                lines.append(
                    f"  {name:<16} {row.worked_hours:>9.2f}  "
                    f"{row.target_hours:>9.2f}  {_signed(row.balance):>10}"
                )

        return "\n".join(lines)

    # ─────────────────────────── Document Collection ─────────────────────────

    def _collect_documents(
        self, data: ReportData
    ) -> tuple[list[tuple[str, date, str]], list[tuple[str, date, str]]]:
        """Returns (image_docs, pdf_docs) for records in the report period.
        Each element: (type_label, record_date, file_path).
        Only includes paths that actually exist on disk.
        """
        start, end = period_range(data.period_type, data.year, data.month, data.quarter)

        image_exts = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".gif"}
        image_docs: list[tuple[str, date, str]] = []
        pdf_docs: list[tuple[str, date, str]] = []

        for rec in self._model_sickness.get_records_in_date_range(start, end):
            if rec.document_path and Path(rec.document_path).exists():
                ext = Path(rec.document_path).suffix.lower()
                if ext == ".pdf":
                    pdf_docs.append(("Sickness", rec.date, rec.document_path))
                elif ext in image_exts:
                    image_docs.append(("Sickness", rec.date, rec.document_path))

        for rec in self._model_tc.get_records_for_date_range(start, end):
            if rec.document_path and Path(rec.document_path).exists():
                ext = Path(rec.document_path).suffix.lower()
                if ext == ".pdf":
                    pdf_docs.append(("Road", rec.date, rec.document_path))
                elif ext in image_exts:
                    image_docs.append(("Road", rec.date, rec.document_path))

        if self._model_miliuim is not None:
            for rec in self._model_miliuim.get_records_in_date_range(start, end):
                if rec.document_path and Path(rec.document_path).exists():
                    ext = Path(rec.document_path).suffix.lower()
                    if ext == ".pdf":
                        pdf_docs.append(("Miliuim", rec.start_date, rec.document_path))
                    elif ext in image_exts:
                        image_docs.append(
                            ("Miliuim", rec.start_date, rec.document_path)
                        )

        return image_docs, pdf_docs

    # ─────────────────────────── PDF Export ─────────────────────────────────

    def _do_export_pdf(self) -> None:
        data = self._get_report_data()
        if data is None:
            return

        filepath = asksaveasfilename(
            parent=self,
            title="Save PDF Report",
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
            initialfile=f"timeclock_report_{data.period_label.replace(' ', '_')}.pdf",
        )
        if not filepath:
            return

        try:
            self._generate_pdf(data, filepath)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            # reportlab/pypdf and file I/O can raise many different exception
            # types; report to the user and log rather than crash the dialog.
            logger.exception(
                "Failed to generate PDF report for period=%s path=%s",
                data.period_label,
                filepath,
            )
            messagebox.showerror(
                "Export Failed", f"Could not generate PDF:\n{exc}", parent=self
            )
            return

        messagebox.showinfo(
            "PDF Exported",
            f"Report saved to:\n{filepath}",
            parent=self,
        )

    def _generate_pdf(self, data: ReportData, filepath: str) -> None:
        styles = getSampleStyleSheet()

        def kv_table(rows: list[list[str]]) -> Table:
            """Two-column key/value table."""
            t = Table(rows, colWidths=[7 * cm, 9 * cm])
            t.setStyle(
                TableStyle(
                    [
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f5f5f5")),
                        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, -1), 10),
                        ("LEFTPADDING", (0, 0), (-1, -1), 8),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                        ("TOPPADDING", (0, 0), (-1, -1), 5),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ]
                )
            )
            return t

        def monthly_table(rows: list[list[str]]) -> Table:
            """Multi-column monthly breakdown table with a header row."""
            col_widths = [5.5 * cm, 4 * cm, 4 * cm, 4 * cm]
            t = Table(rows, colWidths=col_widths)
            t.setStyle(
                TableStyle(
                    [
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#d9d9d9")),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, -1), 10),
                        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 8),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                        ("TOPPADDING", (0, 0), (-1, -1), 5),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        (
                            "ROWBACKGROUNDS",
                            (0, 1),
                            (-1, -1),
                            [colors.white, colors.HexColor("#f9f9f9")],
                        ),
                    ]
                )
            )
            return t

        doc = SimpleDocTemplate(
            filepath,
            pagesize=A4,
            title=f"Time Clock Report — {data.period_label}",
            rightMargin=2.5 * cm,
            leftMargin=2.5 * cm,
            topMargin=2.5 * cm,
            bottomMargin=2.5 * cm,
        )

        story = []

        # ── Title ─────────────────────────────────────────────────────────────
        story.append(
            Paragraph(
                f"Time Clock Report — {data.period_label}",
                styles["Title"],
            )
        )
        story.append(Spacer(1, 0.4 * cm))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.grey))
        story.append(Spacer(1, 0.4 * cm))

        # ── Time Clock ────────────────────────────────────────────────────────
        story.append(Paragraph("Time Clock", styles["Heading1"]))
        story.append(Spacer(1, 0.2 * cm))
        story.append(
            kv_table(
                [
                    ["Worked", _fmt_h(data.worked_hours)],
                    ["Target", _fmt_h(data.target_hours)],
                    ["Balance", f"{_signed(data.time_balance)} h"],
                    [
                        "Weighted Overtime",
                        f"{data.weighted_overtime:.2f} h "
                        f" (rate: {data.overtime_rate}x)",
                    ],
                ]
            )
        )
        story.append(Spacer(1, 0.5 * cm))

        # ── Vacation ──────────────────────────────────────────────────────────
        story.append(Paragraph(f"Vacation ({data.year})", styles["Heading1"]))
        story.append(Spacer(1, 0.2 * cm))
        story.append(
            kv_table(
                [
                    ["Allowance", f"{data.vac_allowance:.1f} h"],
                    ["Carry-over", f"{data.vac_carry_over:.1f} h"],
                    ["Total Pool", f"{data.vac_total_pool:.1f} h"],
                    ["Used", f"{data.vac_used:.1f} h"],
                    ["Remaining", f"{data.vac_remaining:.1f} h"],
                ]
            )
        )
        story.append(Spacer(1, 0.5 * cm))

        # ── Sickness ──────────────────────────────────────────────────────────
        story.append(Paragraph(f"Sickness ({data.year})", styles["Heading1"]))
        story.append(Spacer(1, 0.2 * cm))
        story.append(
            kv_table(
                [
                    ["Allowance", f"{data.sick_allowance_hours:.1f} h"],
                    ["Used", f"{data.sick_used_hours:.1f} h"],
                    ["Remaining", f"{data.sick_remaining_hours:.1f} h"],
                ]
            )
        )
        story.append(Spacer(1, 0.5 * cm))

        # ── Miliuim ───────────────────────────────────────────────────────────
        story.append(Paragraph(f"Miliuim ({data.year})", styles["Heading1"]))
        story.append(Spacer(1, 0.2 * cm))
        story.append(
            kv_table(
                [
                    ["Periods", str(data.miliuim_period_count)],
                    ["Total days", str(data.miliuim_total_days)],
                ]
            )
        )

        # ── Monthly Breakdown ─────────────────────────────────────────────────
        if data.monthly_rows:
            story.append(Spacer(1, 0.5 * cm))
            story.append(Paragraph("Monthly Breakdown", styles["Heading1"]))
            story.append(Spacer(1, 0.2 * cm))

            table_rows: list[list[str]] = [
                ["Month", "Worked (h)", "Target (h)", "Balance (h)"]
            ]
            for row in data.monthly_rows:
                table_rows.append(
                    [
                        f"{MONTH_NAMES[row.month]} {row.year}",
                        f"{row.worked_hours:.2f}",
                        f"{row.target_hours:.2f}",
                        _signed(row.balance),
                    ]
                )
            story.append(monthly_table(table_rows))

        # ── Attached Documents (images) ───────────────────────────────────────
        image_docs, pdf_docs = self._collect_documents(data)

        if image_docs:
            story.append(Spacer(1, 0.5 * cm))
            story.append(HRFlowable(width="100%", thickness=1, color=colors.grey))
            story.append(Spacer(1, 0.4 * cm))
            story.append(Paragraph("Attached Documents", styles["Heading1"]))
            for type_label, rec_date, doc_path in image_docs:
                story.append(Spacer(1, 0.3 * cm))
                doc_label = (
                    f"{type_label} — {to_display_date(rec_date)} — "
                    f"{os.path.basename(doc_path)}"
                )
                story.append(
                    Paragraph(
                        doc_label,
                        styles["Heading2"],
                    )
                )
                story.append(Spacer(1, 0.2 * cm))
                img = RLImage(
                    doc_path, width=15 * cm, height=20 * cm, kind="proportional"
                )
                story.append(img)

        doc.build(story)

        # ── Attached Documents (PDF pages appended) ───────────────────────────
        if pdf_docs:
            writer = PdfWriter()
            main_reader = PdfReader(filepath)
            for page in main_reader.pages:
                writer.add_page(page)
            failed_attachments: list[str] = []
            for _type_label, _rec_date, doc_path in pdf_docs:
                try:
                    att_reader = PdfReader(doc_path)
                    for page in att_reader.pages:
                        writer.add_page(page)
                except Exception as exc:  # pylint: disable=broad-exception-caught
                    # A single corrupt/unreadable attachment shouldn't abort the
                    # whole report; log it and surface a warning after export.
                    logger.exception(
                        "Failed to append PDF attachment %s (%s dated %s) to report %s",
                        doc_path,
                        _type_label,
                        _rec_date,
                        filepath,
                    )
                    failed_attachments.append(f"{os.path.basename(doc_path)}: {exc}")
            tmp_fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
            try:
                os.close(tmp_fd)
                with open(tmp_path, "wb") as f:
                    writer.write(f)
                shutil.move(tmp_path, filepath)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except Exception:  # pylint: disable=broad-exception-caught
                    # Best-effort cleanup of the temp file; log rather than
                    # silently swallow so a leaked temp file is traceable, and
                    # don't let a cleanup failure mask the original error below.
                    logger.exception(
                        "Failed to clean up temp file %s after PDF write failure",
                        tmp_path,
                    )
                raise
            if failed_attachments:
                messagebox.showwarning(
                    "Attachment Warning",
                    "Some attachments could not be merged:\n"
                    + "\n".join(failed_attachments),
                    parent=self,
                )
