"""Tests for VacationGrantDialog save/remove logic (no Tk mainloop needed).

Mirrors the ``__new__``-bypass pattern used in
tests/views/test_vacation_record_dialog_pure.py: the dialog's Tk widgets are
stood in with MagicMocks so the save/remove methods can run without a live Tk
interpreter or display, matching this repo's headless-CI constraint.
"""

from datetime import date
from unittest import mock

from domain.enums import WarningCode
from domain.types import Result
from views.vacation_grant_dialog import VacationGrantDialog


def _make_dialog() -> VacationGrantDialog:
    """Stand in the widgets ``_on_save``/``_on_remove`` touch."""
    dialog = VacationGrantDialog.__new__(VacationGrantDialog)
    dialog._get_date = lambda: date(2026, 6, 1)
    dialog._date_widget = mock.MagicMock()
    dialog._lbl_error = mock.MagicMock()
    dialog._var_hours = mock.MagicMock()
    dialog._var_hours.get.return_value = "8.0"
    dialog._var_note = mock.MagicMock()
    dialog._var_note.get.return_value = ""
    dialog._editing_id = None
    dialog._controller = mock.MagicMock()
    dialog._reload = mock.MagicMock()
    return dialog


def test_on_save_builds_grant_and_reloads_on_success() -> None:
    dialog = _make_dialog()
    dialog._var_hours.get.return_value = "12.0"
    dialog._controller.save_grant.return_value = Result(ok=True)

    dialog._on_save()

    dialog._controller.save_grant.assert_called_once()
    grant = dialog._controller.save_grant.call_args.args[0]
    assert grant.id is None
    assert grant.date == date(2026, 6, 1)
    assert grant.hours == 12.0
    dialog._reload.assert_called_once()


def test_on_save_edit_passes_existing_id() -> None:
    dialog = _make_dialog()
    dialog._editing_id = 7
    dialog._controller.save_grant.return_value = Result(ok=True)

    dialog._on_save()

    grant = dialog._controller.save_grant.call_args.args[0]
    assert grant.id == 7


def test_on_save_non_positive_hours_shows_invariant_error() -> None:
    """A zero-hour grant violates the VacationGrant positive-hours invariant;
    it is surfaced inline and never reaches the controller."""
    dialog = _make_dialog()
    dialog._var_hours.get.return_value = "0.0"

    dialog._on_save()

    dialog._controller.save_grant.assert_not_called()
    dialog._reload.assert_not_called()
    dialog._lbl_error.config.assert_called_with(text="Hours must be positive.")


def test_on_save_non_numeric_hours_is_field_error() -> None:
    dialog = _make_dialog()
    dialog._var_hours.get.return_value = "abc"

    dialog._on_save()

    dialog._controller.save_grant.assert_not_called()
    dialog._lbl_error.config.assert_called_with(
        text="Hours must be a number greater than zero."
    )


def test_on_save_bad_date_is_field_error() -> None:
    dialog = _make_dialog()

    def _bad_get_date() -> date:
        raise ValueError("no valid date selected")

    dialog._get_date = _bad_get_date

    dialog._on_save()

    dialog._controller.save_grant.assert_not_called()
    dialog._lbl_error.config.assert_called_with(text="Invalid date.")


def test_on_save_controller_error_is_surfaced() -> None:
    dialog = _make_dialog()
    dialog._controller.save_grant.return_value = Result(
        ok=False, errors=("Database error.",)
    )

    dialog._on_save()

    dialog._reload.assert_not_called()
    dialog._lbl_error.config.assert_called_with(text="Database error.")


def test_on_remove_without_selection_shows_info_and_does_not_delete() -> None:
    dialog = _make_dialog()
    dialog._editing_id = None

    with mock.patch("views.vacation_grant_dialog.messagebox") as messagebox_mock:
        dialog._on_remove()

    messagebox_mock.showinfo.assert_called_once()
    dialog._controller.delete_grant.assert_not_called()


def test_on_remove_confirmed_deletes_and_reloads() -> None:
    dialog = _make_dialog()
    dialog._editing_id = 5
    dialog._controller.delete_grant.return_value = Result(ok=True)

    with mock.patch("views.vacation_grant_dialog.messagebox") as messagebox_mock:
        messagebox_mock.askyesno.return_value = True
        dialog._on_remove()

    dialog._controller.delete_grant.assert_called_once_with(5)
    dialog._reload.assert_called_once()


def test_on_remove_declined_does_not_delete() -> None:
    dialog = _make_dialog()
    dialog._editing_id = 5

    with mock.patch("views.vacation_grant_dialog.messagebox") as messagebox_mock:
        messagebox_mock.askyesno.return_value = False
        dialog._on_remove()

    dialog._controller.delete_grant.assert_not_called()
    dialog._reload.assert_not_called()


def test_on_remove_record_not_found_reloads_without_error_box() -> None:
    """A RECORD_NOT_FOUND race means the grant was already gone — reload drops
    the phantom row and no error box is shown."""
    dialog = _make_dialog()
    dialog._editing_id = 5
    dialog._controller.delete_grant.return_value = Result(
        ok=False, errors=(WarningCode.RECORD_NOT_FOUND.value,)
    )

    with mock.patch("views.vacation_grant_dialog.messagebox") as messagebox_mock:
        messagebox_mock.askyesno.return_value = True
        dialog._on_remove()

    messagebox_mock.showerror.assert_not_called()
    dialog._reload.assert_called_once()
