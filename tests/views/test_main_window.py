"""Tests for MainWindow's error-dedup logic (`_show_error_deduped` and its
three callers: `_on_bus_handler_error`, `_on_tk_callback_exception`, and
`notify_settings_error`).

This repo's CI runs headless with no X display (see tests/views/
test_help_viewer_dialogs.py and test_time_clock_tab_dedup.py for the same
constraint on other view modules), so `MainWindow` is built via
`MainWindow.__new__` (bypassing `__init__`, which constructs a real
ttk.Frame, menu, notebook, and subscribes to the bus) with only the
attributes the methods under test actually touch: `root` and
`_last_error_shown_at`. This mirrors the `_make_tab`/`_make_tray` bypass
pattern in test_time_clock_tab_dedup.py and test_tray_thread_safety.py.

`tkinter.messagebox.showerror` is patched at `views.main_window.messagebox`
(the module-level import site) so no real modal dialog is ever created.
`time.monotonic` is patched at `views.main_window.time.monotonic` (the
module imports `time` itself, not `from time import monotonic`) to control
the dedupe window deterministically without real wall-clock waits.
"""

import sys
from unittest import mock

from views.main_window import MainWindow


class _FakeRoot:
    """Stand-in for tk.Tk -- records `after()` calls without executing them,
    so tests can assert a callback was scheduled (not run inline) and then
    invoke it manually to inspect what it does."""

    def __init__(self) -> None:
        self.after_calls: list[tuple] = []

    def after(self, delay, callback, *args):
        self.after_calls.append((delay, callback, args))
        return f"after_id_{len(self.after_calls)}"


def _make_window(root=None) -> MainWindow:
    """Builds a MainWindow without running __init__ / constructing any real
    Tk widgets -- only the attributes touched by the error-dedup methods
    are set."""
    win = MainWindow.__new__(MainWindow)
    win.root = root if root is not None else _FakeRoot()
    win._last_error_shown_at = {}
    return win


def _raise_value_error(msg: str) -> None:
    """Helper that raises at the same source line every call, so two
    invocations produce tracebacks whose innermost frame shares file:line
    but whose exception messages differ -- used to prove the dedupe key is
    built from type+site, not str(val)."""
    raise ValueError(msg)


# ---------------------------------------------------------------------------
# _show_error_deduped
# ---------------------------------------------------------------------------


def test_show_error_deduped_first_call_shows_dialog():
    win = _make_window()
    with mock.patch("views.main_window.messagebox.showerror") as mock_error:
        win._show_error_deduped("k1", "Title", "Message")

    mock_error.assert_called_once_with("Title", "Message", parent=win.root)


def test_show_error_deduped_second_call_within_window_is_suppressed():
    win = _make_window()
    with mock.patch("views.main_window.messagebox.showerror") as mock_error:
        with mock.patch("views.main_window.time.monotonic", return_value=100.0):
            win._show_error_deduped("k1", "Title", "Message")
        with mock.patch("views.main_window.time.monotonic", return_value=102.0):
            win._show_error_deduped("k1", "Title", "Message")

    mock_error.assert_called_once()


def test_show_error_deduped_third_call_after_window_elapses_shows_again():
    win = _make_window()
    with mock.patch("views.main_window.messagebox.showerror") as mock_error:
        with mock.patch("views.main_window.time.monotonic", return_value=100.0):
            win._show_error_deduped("k1", "Title", "Message")
        with mock.patch("views.main_window.time.monotonic", return_value=102.0):
            win._show_error_deduped("k1", "Title", "Message")
        with mock.patch(
            "views.main_window.time.monotonic",
            return_value=100.0 + MainWindow._ERROR_DEDUPE_WINDOW_SECONDS + 0.1,
        ):
            win._show_error_deduped("k1", "Title", "Message")

    assert mock_error.call_count == 2


def test_show_error_deduped_different_key_shows_even_within_window():
    win = _make_window()
    with mock.patch("views.main_window.messagebox.showerror") as mock_error:
        with mock.patch("views.main_window.time.monotonic", return_value=100.0):
            win._show_error_deduped("k1", "Title A", "Message A")
        with mock.patch("views.main_window.time.monotonic", return_value=100.5):
            win._show_error_deduped("k2", "Title B", "Message B")

    assert mock_error.call_count == 2
    mock_error.assert_any_call("Title A", "Message A", parent=win.root)
    mock_error.assert_any_call("Title B", "Message B", parent=win.root)


def test_show_error_deduped_prunes_old_keys_after_window_elapses():
    win = _make_window()
    with mock.patch("views.main_window.messagebox.showerror"):
        with mock.patch("views.main_window.time.monotonic", return_value=100.0):
            win._show_error_deduped("k1", "Title", "Message")
        assert "k1" in win._last_error_shown_at

        # A later, unrelated call (different key) after the window has
        # elapsed for k1 must prune k1 out of the tracking dict.
        with mock.patch(
            "views.main_window.time.monotonic",
            return_value=100.0 + MainWindow._ERROR_DEDUPE_WINDOW_SECONDS + 0.1,
        ):
            win._show_error_deduped("k2", "Title", "Message")

    assert "k1" not in win._last_error_shown_at
    assert "k2" in win._last_error_shown_at


# ---------------------------------------------------------------------------
# _on_bus_handler_error
# ---------------------------------------------------------------------------


def test_on_bus_handler_error_defers_via_root_after_not_shown_inline():
    root = _FakeRoot()
    win = _make_window(root)

    with mock.patch("views.main_window.messagebox.showerror") as mock_error:
        win._on_bus_handler_error("boom")
        mock_error.assert_not_called()

        assert len(root.after_calls) == 1
        delay, callback, args = root.after_calls[0]
        assert delay == 0

        callback(*args)

    mock_error.assert_called_once()


def test_on_bus_handler_error_dedupe_key_prefixed_bus():
    root = _FakeRoot()
    win = _make_window(root)

    win._on_bus_handler_error("something failed")
    _delay, callback, args = root.after_calls[0]
    with mock.patch("views.main_window.messagebox.showerror"):
        callback(*args)

    assert "bus:something failed" in win._last_error_shown_at


# ---------------------------------------------------------------------------
# _on_tk_callback_exception
# ---------------------------------------------------------------------------


def test_on_tk_callback_exception_shows_synchronously_no_after():
    root = _FakeRoot()
    win = _make_window(root)

    try:
        _raise_value_error("first message")
    except ValueError:
        exc, val, tb = sys.exc_info()

    with mock.patch("views.main_window.messagebox.showerror") as mock_error:
        win._on_tk_callback_exception(exc, val, tb)

    mock_error.assert_called_once()
    assert root.after_calls == []


def test_on_tk_callback_exception_dedupe_key_uses_type_and_site_not_message():
    """Two exceptions of the same type raised at the same source line, but
    with different messages, must dedupe against each other -- the key is
    built from exc.__name__ + file:line, not str(val)."""
    win = _make_window()

    try:
        _raise_value_error("first message")
    except ValueError:
        exc1, val1, tb1 = sys.exc_info()

    try:
        _raise_value_error("second message, totally different")
    except ValueError:
        exc2, val2, tb2 = sys.exc_info()

    with mock.patch("views.main_window.messagebox.showerror") as mock_error:
        with mock.patch("views.main_window.time.monotonic", return_value=100.0):
            win._on_tk_callback_exception(exc1, val1, tb1)
        with mock.patch("views.main_window.time.monotonic", return_value=100.5):
            win._on_tk_callback_exception(exc2, val2, tb2)

    # Same type+site -> same key -> second call suppressed by dedupe.
    mock_error.assert_called_once()
    assert len(win._last_error_shown_at) == 1


def test_on_tk_callback_exception_no_frames_falls_back_to_unknown():
    win = _make_window()
    exc = ValueError
    val = ValueError("no traceback here")

    with mock.patch("views.main_window.messagebox.showerror") as mock_error:
        win._on_tk_callback_exception(exc, val, None)

    mock_error.assert_called_once()
    assert any(
        key.startswith("tk:ValueError:unknown") for key in win._last_error_shown_at
    )


# ---------------------------------------------------------------------------
# notify_settings_error
# ---------------------------------------------------------------------------


def test_notify_settings_error_defers_via_root_after_with_settings_prefix():
    root = _FakeRoot()
    win = _make_window(root)

    with mock.patch("views.main_window.messagebox.showerror") as mock_error:
        win.notify_settings_error("theme", "DB read failed")
        mock_error.assert_not_called()

        assert len(root.after_calls) == 1
        delay, callback, args = root.after_calls[0]
        assert delay == 0

        callback(*args)

    mock_error.assert_called_once()
    assert "settings:theme" in win._last_error_shown_at
