"""Regression tests for ReportDialog document collection (no Tk mainloop needed)."""

from datetime import date, time
from types import SimpleNamespace

from db.database import Database
from core.events import EventBus
from domain.enums import WorkType
from domain.types import TimeRecord, SicknessRecord
from models.time_clock_model import TimeClockModel
from models.sickness_model import SicknessModel
from views.report_dialog import ReportDialog


def _make_dialog(model_tc, model_sickness, model_miliuim=None):
    """Builds a ReportDialog instance without running its Tk __init__/mainloop,
    since _collect_documents only touches the model attributes it sets."""
    dialog = ReportDialog.__new__(ReportDialog)
    dialog._model_tc = model_tc
    dialog._model_sickness = model_sickness
    dialog._model_miliuim = model_miliuim
    return dialog


def test_collect_documents_includes_road_time_records(db: Database, event_bus: EventBus, tmp_path) -> None:
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
    data = SimpleNamespace(
        period_type="month", year=2026, month=6, quarter=None)

    image_docs, pdf_docs = dialog._collect_documents(data)

    assert len(pdf_docs) == 1
    type_label, rec_date, path = pdf_docs[0]
    assert type_label == "Road"
    assert rec_date == date(2026, 6, 15)
    assert path == str(doc_path)
    assert image_docs == []


def test_collect_documents_ignores_records_without_document(db: Database, event_bus: EventBus) -> None:
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
    data = SimpleNamespace(
        period_type="month", year=2026, month=6, quarter=None)

    image_docs, pdf_docs = dialog._collect_documents(data)
    assert image_docs == []
    assert pdf_docs == []


def test_collect_documents_still_includes_sickness_docs(db: Database, event_bus: EventBus, tmp_path) -> None:
    tc_model = TimeClockModel(db, event_bus)
    sick_model = SicknessModel(db, event_bus)

    doc_path = tmp_path / "sick_note.png"
    doc_path.write_bytes(b"fake image bytes")

    sick_model.insert_record(SicknessRecord(
        id=None, date=date(2026, 6, 20), hours=8.0,
        document_path=str(doc_path),
    ))

    dialog = _make_dialog(tc_model, sick_model)
    data = SimpleNamespace(
        period_type="month", year=2026, month=6, quarter=None)

    image_docs, pdf_docs = dialog._collect_documents(data)
    assert len(image_docs) == 1
    assert image_docs[0][0] == "Sickness"
    assert pdf_docs == []
