"""Regression tests for ReportDialog document collection (no Tk mainloop needed)."""

import logging
import os
from datetime import date, time
from types import SimpleNamespace
from unittest import mock

import pytest
from pypdf import PdfWriter

from core.events import EventBus
from core.report import ReportData
from db.database import Database
from domain.enums import PeriodType, WorkType
from domain.types import Hours, SicknessRecord, TimeRecord
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
            hours=Hours(8.0),
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
    manager = mock.MagicMock()
    show_warning = manager.showwarning
    show_info = manager.showinfo
    monkeypatch.setattr("views.report_dialog.messagebox.showwarning", show_warning)
    monkeypatch.setattr("views.report_dialog.messagebox.showinfo", show_info)

    dialog._do_export_pdf()

    dialog._generate_pdf.assert_called_once()
    show_warning.assert_called_once()
    warning_text = show_warning.call_args.args[1]
    assert "5 record(s) skipped due to data errors" in warning_text
    show_info.assert_called_once()
    assert [c[0] for c in manager.mock_calls] == ["showwarning", "showinfo"]


# ─────────── real _generate_pdf: atomic-swap leaves no partial file ──────────
#
# The `_do_export_pdf` tests above mock `_generate_pdf` wholesale, so the
# real temp-file/os.replace() dance inside `_generate_pdf` (build the report
# body into `filepath + ".tmp"`, optionally merge attachment pages into
# `filepath + ".merge.tmp"`, then a single final os.replace() into place, with
# a try/finally cleaning leftovers) has zero direct coverage. The tests below
# drive the genuine method against real models on the in-memory `db` fixture.


def _write_minimal_pdf(path) -> None:
    """Write a valid single-page PDF that pypdf's ``PdfReader`` can parse.

    Used as a mergeable report attachment so the ``pdf_docs`` branch of
    ``_generate_pdf`` runs and creates the ``filepath + ".merge.tmp"``
    artifact whose cleanup we assert on. A byte-string like ``b"%PDF fake"``
    would not survive ``PdfReader``, so a real writer is used.
    """
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with open(path, "wb") as handle:
        writer.write(handle)


def _make_pdf_export_dialog(db: Database, event_bus: EventBus):
    """Headless ``ReportDialog`` wired to real time-clock and sickness models.

    Backed by the empty in-memory ``db`` so the real ``_generate_pdf`` (and the
    ``_collect_documents`` call it makes) runs end-to-end without a live Tk
    interpreter. Returns the dialog together with its time-clock model so a
    test can seed a ROAD record carrying a PDF attachment.
    """
    tc_model = TimeClockModel(db, event_bus)
    dialog = _make_dialog(tc_model, SicknessModel(db, event_bus))
    return dialog, tc_model


def _raise_oserror(*_args, **_kwargs) -> None:
    """Stand-in for ``os.replace`` that fails the final atomic swap."""
    raise OSError("simulated atomic-swap failure")


@pytest.mark.parametrize(
    "with_pdf_attachment",
    [False, True],
    ids=["no-attachments", "with-pdf-attachment"],
)
def test_generate_pdf_replace_failure_leaves_no_file_or_temps(
    db: Database,
    event_bus: EventBus,
    tmp_path,
    monkeypatch,
    with_pdf_attachment: bool,
) -> None:
    """If the final os.replace() fails, nothing may remain at ``filepath`` and
    both sibling temps must be cleaned by the ``finally`` block.

    The ``with-pdf-attachment`` case additionally exercises the merge branch:
    a valid PDF on an in-period ROAD record forces creation of
    ``filepath + ".merge.tmp"``, which must also be gone after the failure.
    Writing straight to ``filepath`` (the pre-atomic behaviour) would leave a
    complete-looking report there even though the export raised.
    """
    dialog, tc_model = _make_pdf_export_dialog(db, event_bus)
    if with_pdf_attachment:
        attachment = tmp_path / "receipt.pdf"
        _write_minimal_pdf(attachment)
        tc_model.insert_record(
            TimeRecord(
                id=None,
                date=date(2026, 6, 15),
                start_time=time(8, 0),
                end_time=time(16, 0),
                break_minutes=30,
                work_type=WorkType.ROAD,
                document_path=str(attachment),
            )
        )

    filepath = str(tmp_path / "report.pdf")
    assert not os.path.exists(filepath)  # guard: the swap target starts absent
    monkeypatch.setattr(os, "replace", _raise_oserror)

    with pytest.raises(OSError):
        dialog._generate_pdf(_make_report_data(), filepath)

    assert not os.path.exists(filepath)
    assert not os.path.exists(filepath + ".tmp")
    assert not os.path.exists(filepath + ".merge.tmp")


def test_generate_pdf_success_writes_pdf_and_leaves_no_temps(
    db: Database, event_bus: EventBus, tmp_path
) -> None:
    """The happy path writes a non-empty PDF at ``filepath`` (no attachments)
    and leaves neither sibling temp behind after the atomic swap succeeds."""
    dialog, _tc_model = _make_pdf_export_dialog(db, event_bus)
    filepath = str(tmp_path / "report.pdf")

    dialog._generate_pdf(_make_report_data(), filepath)

    assert os.path.exists(filepath)
    assert os.path.getsize(filepath) > 0
    assert not os.path.exists(filepath + ".tmp")
    assert not os.path.exists(filepath + ".merge.tmp")
    with open(filepath, "rb") as handle:
        assert handle.read(5) == b"%PDF-"
