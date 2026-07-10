"""Date picker: tkcalendar.DateEntry wrapper with pure-Tk fallback."""

from tkcalendar import DateEntry


def make_date_picker(parent, **kwargs):
    """Creates a date picker widget. Returns (widget, get_date, set_date)."""
    picker = DateEntry(parent, date_pattern="dd/mm/yyyy", **kwargs)
    return picker, picker.get_date, picker.set_date
