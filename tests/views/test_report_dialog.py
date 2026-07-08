"""Regression tests for ReportDialog document collection (no Tk mainloop needed)."""

import logging
from datetime import date, time
from types import SimpleNamespace
from unittest import mock

import pytest

from core.events import EventBus
from core.report import ReportData
from db.database import Database
from domain.enums import PeriodType, WorkType
from domain.types import SicknessRecord, TimeRecord
from models.sickness_model import SicknessModel
from models.time_clock_model import TimeClockModel
from views.report_dialog import ReportDialog


def _make_dialog(model_tc, model_sickness, model_miliuim=None):
    """Builds a ReportDialog instance without running its Tk __init__/mainloop,
    since _collect_documents only touches the model attributes it sets."""
    dialog = ReportDialog.__new__(ReportDialog)
    dialog._model_tc = model_tc
    dialog._model_sickness = model_sickness
    dialog._model_miliuim = model_miliuim
    return dialog


def test_collect_documents_includes_road_time_records(
    db: Database, event_bus: EventBus, tmp_path
) -> None:
    tc_model = TimeClockModel(db, event_bus)
    sick_model = SicknessModel(db, event_bus)

    doc_path = tmp_path / "road_receipt.pdf"
    doc_path.write_bytes(b"%PDF-1.4 fake")

    rec = TimeRecord(
        id=None,
        date=date(2026, 6, 15),
        start_time=time(8, 0),
        end_time=time(16, 0),
        break_minutes=30,
        work_type=WorkType.ROAD,
        document_path=str(doc_path),
    )
    tc_model.insert_record(rec)

    dialog = _make_dialog(tc_model, sick_model)
    data = SimpleNamespace(period_type="month", year=2026, month=6, quarter=None)

    image_docs, pdf_docs = dialog._collect_documents(data)

    assert len(pdf_docs) == 1
    type_label, rec_date, path = pdf_docs[0]
    assert type_label == "Road"
    assert rec_date == date(2026, 6, 15)
    assert path == str(doc_path)
    assert image_docs == []


def test_collect_documents_ignores_records_without_document(
    db: Database, event_bus: EventBus
) -> None:
    tc_model = TimeClockModel(db, event_bus)
    sick_model = SicknessModel(db, event_bus)

    rec = TimeRecord(
        id=None,
        date=date(2026, 6, 16),
        start_time=time(8, 0),
        end_time=time(16, 0),
        break_minutes=0,
        work_type=WorkType.IN_SITE,
        office="Main Office",
    )
    tc_model.insert_record(rec)

    dialog = _make_dialog(tc_model, sick_model)
    data = SimpleNamespace(period_type="month", year=2026, month=6, quarter=None)

    image_docs, pdf_docs = dialog._collect_documents(data)
    assert image_docs == []
    assert pdf_docs == []


def test_collect_documents_still_includes_sickness_docs(
    db: Database, event_bus: EventBus, tmp_path
) -> None:
    tc_model = TimeClockModel(db, event_bus)
    sick_model = SicknessModel(db, event_bus)

    doc_path = tmp_path / "sick_note.png"
    doc_path.write_bytes(b"fake image bytes")

    sick_model.insert_record(
        SicknessRecord(
            id=None,
            date=date(2026, 6, 20),
            hours=8.0,
            document_path=str(doc_path),
        )
    )

    dialog = _make_dialog(tc_model, sick_model)
    data = SimpleNamespace(period_type="month", year=2026, month=6, quarter=None)

    image_docs, pdf_docs = dialog._collect_documents(data)
    assert len(image_docs) == 1
    assert image_docs[0][0] == "Sickness"
    assert pdf_docs == []


def _make_report_data_dialog(year="2026", period="month", month="June", quarter="Q1"):
    """Builds a ReportDialog with just the form Vars needed by
    _get_report_data, bypassing Tk __init__/mainloop like _make_dialog above."""
    dialog = ReportDialog.__new__(ReportDialog)
    dialog._var_year = mock.MagicMock(get=mock.MagicMock(return_value=year))
    dialog._var_period = mock.MagicMock(get=mock.MagicMock(return_value=period))
    dialog._var_month = mock.MagicMock(get=mock.MagicMock(return_value=month))
    dialog._var_quarter = mock.MagicMock(get=mock.MagicMock(return_value=quarter))
    dialog._model_tc = mock.MagicMock()
    dialog._model_vacation = mock.MagicMock()
    dialog._model_sickness = mock.MagicMock()
    dialog._model_miliuim = mock.MagicMock()
    dialog._settings = mock.MagicMock()
    return dialog


def test_get_report_data_period_summary_failure_is_logged_not_swallowed(
    caplog: pytest.LogCaptureFixture, monkeypatch
) -> None:
    """A period_summary() failure must show up in the log (with the period
    that was being assembled) instead of vanishing into a bare
    messagebox.showerror with no trace anywhere else."""
    dialog = _make_report_data_dialog(year="2026", period="month", month="June")

    monkeypatch.setattr(
        "views.report_dialog.period_summary",
        mock.MagicMock(side_effect=RuntimeError("db unavailable")),
    )
    show_error = mock.MagicMock()
    monkeypatch.setattr("views.report_dialog.messagebox.showerror", show_error)

    with caplog.at_level(logging.ERROR, logger="views.report_dialog"):
        result = dialog._get_report_data()

    assert result is None
    show_error.assert_called_once()
    assert any(record.levelno >= logging.ERROR for record in caplog.records)
    logged_text = " ".join(record.getMessage() for record in caplog.records)
    assert "month" in logged_text
    assert "2026" in logged_text


# ─────────── skipped_record_count surfaced to the user ───────────────────────


def _make_report_data(skipped_record_count: int = 0) -> ReportData:
    """Minimal but fully-populated ReportData for preview/export tests --
    only skipped_record_count varies between cases."""
    return ReportData(
        period_label="June 2026",
        period_type=PeriodType.MONTH,
        year=2026,
        month=6,
        quarter=None,
        worked_hours=160.0,
        target_hours=160.0,
        time_balance=0.0,
        weighted_overtime=0.0,
        overtime_rate=1.0,
        vac_allowance=0.0,
        vac_carry_over=0.0,
        vac_total_pool=0.0,
        vac_used=0.0,
        vac_remaining=0.0,
        sick_allowance_hours=80.0,
        sick_used_hours=0.0,
        sick_remaining_hours=80.0,
        miliuim_period_count=0,
        miliuim_total_days=0,
        skipped_record_count=skipped_record_count,
    )


def test_build_preview_text_no_warning_when_nothing_skipped() -> None:
    dialog = ReportDialog.__new__(ReportDialog)
    text = dialog._build_preview_text(_make_report_data(skipped_record_count=0))
    assert "skipped" not in text.lower()


def test_build_preview_text_warns_when_records_skipped() -> None:
    dialog = ReportDialog.__new__(ReportDialog)
    text = dialog._build_preview_text(_make_report_data(skipped_record_count=2))
    assert "2 record(s) skipped due to data errors" in text


def _make_export_pdf_dialog(data: ReportData) -> ReportDialog:
    dialog = ReportDialog.__new__(ReportDialog)
    dialog._get_report_data = lambda: data
    dialog._generate_pdf = mock.MagicMock()
    return dialog


def test_export_pdf_no_warning_when_nothing_skipped(tmp_path, monkeypatch) -> None:
    dialog = _make_export_pdf_dialog(_make_report_data(skipped_record_count=0))
    filepath = str(tmp_path / "report.pdf")
    monkeypatch.setattr("views.report_dialog.asksaveasfilename", lambda **_kw: filepath)
    show_warning = mock.MagicMock()
    show_info = mock.MagicMock()
    monkeypatch.setattr("views.report_dialog.messagebox.showwarning", show_warning)
    monkeypatch.setattr("views.report_dialog.messagebox.showinfo", show_info)

    dialog._do_export_pdf()

    dialog._generate_pdf.assert_called_once()
    show_warning.assert_not_called()
    show_info.assert_called_once()


def test_export_pdf_warns_when_records_skipped(tmp_path, monkeypatch) -> None:
    """A skipped-record warning must be shown before the "PDF Exported"
    success dialog, so the user sees the caveat rather than the report
    silently presenting as complete."""
    dialog = _make_export_pdf_dialog(_make_report_data(skipped_record_count=5))
    filepath = str(tmp_path / "report.pdf")
    monkeypatch.setattr("views.report_dialog.asksaveasfilename", lambda **_kw: filepath)
    show_warning = mock.MagicMock()
    show_info = mock.MagicMock()
    monkeypatch.setattr("views.report_dialog.messagebox.showwarning", show_warning)
    monkeypatch.setattr("views.report_dialog.messagebox.showinfo", show_info)

    dialog._do_export_pdf()

    dialog._generate_pdf.assert_called_once()
    show_warning.assert_called_once()
    warning_text = show_warning.call_args.args[1]
    assert "5 record(s) skipped due to data errors" in warning_text
    show_info.assert_called_once()
