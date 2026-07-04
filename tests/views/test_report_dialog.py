"""Regression tests for ReportDialog document collection (no Tk mainloop needed)."""

import logging
from datetime import date, time
from types import SimpleNamespace
from unittest import mock

import pytest

from core.events import EventBus
from db.database import Database
from domain.enums import WorkType
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
