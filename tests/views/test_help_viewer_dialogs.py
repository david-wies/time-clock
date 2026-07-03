"""Tests for open_help() error paths and the report/suggest dialog submit flow.

This repository's CI runs `pytest tests/` on a headless Ubuntu runner with
no X display configured (see .github/workflows/ci.yml), so real
tkinter.Tk()/Toplevel() calls raise TclError there. tests/views/
test_report_dialog.py works around this by building its subject via
``ReportDialog.__new__`` and calling only the pure method under test.
``_report_dialog`` in views/help_viewer.py has no such bypass -- its
validation and webbrowser-open handling live entirely inside the
``_on_submit`` closure defined mid-function -- so instead every
tkinter/ttk constructor it touches is monkeypatched to a MagicMock stand-in
and the Submit button's captured ``command`` callback (``_on_submit``
itself) is invoked directly. This keeps the tests fast and display-free
while still exercising the real validation and error-handling branches.
"""
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from urllib.parse import parse_qs, urlparse
import webbrowser

import pytest

from views import help_viewer


def _open_dialog(monkeypatch, kind):
    """Builds the ``kind`` report dialog with all Tk/ttk widgets mocked out.

    Every constructor ``_report_dialog`` calls (Toplevel, Frame, Label,
    Entry, Button, StringVar, Text) is replaced with a MagicMock so the
    function can run to completion without a live Tk interpreter. The
    StringVar/Text instances are captured in the order ``_report_dialog``
    creates them -- name, then email, then the message Text widget -- and
    the 'Submit' ttk.Button's ``command`` kwarg is captured directly,
    since that callback *is* the private ``_on_submit`` closure under
    test.

    Returns a ``SimpleNamespace`` exposing ``dialog`` (the mocked
    Toplevel), ``name_var``, ``email_var``, ``message`` (the mocked Text
    widget), and ``submit`` (the zero-arg callable to trigger submission).
    Callers set ``.get.return_value`` on ``name_var``/``email_var``/
    ``message`` to simulate user input before calling ``submit()``.
    """
    created_vars = []
    created_texts = []
    submit_holder = {}

    def _fake_stringvar(*_args, **_kwargs):
        var = mock.MagicMock()
        created_vars.append(var)
        return var

    def _fake_text(*_args, **_kwargs):
        widget = mock.MagicMock()
        created_texts.append(widget)
        return widget

    def _fake_button(*_args, **kwargs):
        widget = mock.MagicMock()
        if kwargs.get('text') == 'Submit':
            submit_holder['command'] = kwargs.get('command')
        return widget

    dialog = mock.MagicMock()
    monkeypatch.setattr(help_viewer.tk, 'Toplevel', lambda *_a, **_k: dialog)
    monkeypatch.setattr(
        help_viewer.ttk, 'Frame', lambda *_a, **_k: mock.MagicMock())
    monkeypatch.setattr(
        help_viewer.ttk, 'Label', lambda *_a, **_k: mock.MagicMock())
    monkeypatch.setattr(
        help_viewer.ttk, 'Entry', lambda *_a, **_k: mock.MagicMock())
    monkeypatch.setattr(help_viewer.ttk, 'Button', _fake_button)
    monkeypatch.setattr(help_viewer.tk, 'StringVar', _fake_stringvar)
    monkeypatch.setattr(help_viewer.tk, 'Text', _fake_text)

    help_viewer._report_dialog(None, kind)

    name_var, email_var = created_vars
    return SimpleNamespace(
        dialog=dialog,
        name_var=name_var,
        email_var=email_var,
        message=created_texts[0],
        submit=submit_holder['command'],
    )


def test_open_help_missing_file_shows_warning_and_does_not_open_browser(monkeypatch):
    monkeypatch.setattr(Path, 'exists', lambda self: False)
    mock_warn = mock.MagicMock()
    monkeypatch.setattr(help_viewer.messagebox, 'showwarning', mock_warn)
    mock_open = mock.MagicMock()
    monkeypatch.setattr(help_viewer.webbrowser, 'open', mock_open)

    help_viewer.open_help()

    mock_warn.assert_called_once()
    mock_open.assert_not_called()


def test_open_help_existing_file_opens_in_browser(monkeypatch):
    monkeypatch.setattr(Path, 'exists', lambda self: True)
    mock_open = mock.MagicMock(return_value=True)
    monkeypatch.setattr(help_viewer.webbrowser, 'open', mock_open)

    help_viewer.open_help()

    mock_open.assert_called_once()
    (uri,), _kwargs = mock_open.call_args
    assert uri.startswith('file://')
    assert uri.endswith('help/index.html')


def test_open_help_browser_returns_false_shows_error_message(monkeypatch):
    monkeypatch.setattr(Path, 'exists', lambda self: True)
    monkeypatch.setattr(help_viewer.webbrowser, 'open', mock.MagicMock(return_value=False))
    mock_error = mock.MagicMock()
    monkeypatch.setattr(help_viewer.messagebox, 'showerror', mock_error)

    help_viewer.open_help()

    mock_error.assert_called_once()


def test_open_help_webbrowser_error_shows_error_message(monkeypatch):
    monkeypatch.setattr(Path, 'exists', lambda self: True)
    monkeypatch.setattr(
        help_viewer.webbrowser, 'open',
        mock.MagicMock(side_effect=webbrowser.Error('no browser registered')),
    )
    mock_error = mock.MagicMock()
    monkeypatch.setattr(help_viewer.messagebox, 'showerror', mock_error)

    help_viewer.open_help()

    mock_error.assert_called_once()
    assert 'no browser registered' in mock_error.call_args[0][1]


def test_open_help_oserror_shows_error_message(monkeypatch):
    """webbrowser.open() can raise a plain OSError (e.g. the registered
    browser binary was removed/broken) rather than webbrowser.Error --
    UnixBrowser._invoke() calls subprocess.Popen with no try/except."""
    monkeypatch.setattr(Path, 'exists', lambda self: True)
    monkeypatch.setattr(
        help_viewer.webbrowser, 'open',
        mock.MagicMock(side_effect=OSError('no such file or directory')),
    )
    mock_error = mock.MagicMock()
    monkeypatch.setattr(help_viewer.messagebox, 'showerror', mock_error)

    help_viewer.open_help()

    mock_error.assert_called_once()
    assert 'no such file or directory' in mock_error.call_args[0][1]


@pytest.mark.parametrize(
    ('name', 'email', 'message'),
    [
        ('', 'jane@example.com', 'a message'),
        ('Jane', '', 'a message'),
        ('Jane', 'not-an-email', 'a message'),
        ('Jane', 'jane@example', 'a message'),
        ('Jane', 'a@', 'a message'),
        ('Jane', 'jane@example.com', ''),
        ('Jane', 'jane@example.com', '   '),
    ],
    ids=[
        'missing-name',
        'missing-email',
        'email-without-at-sign',
        'email-without-domain-dot',
        'email-garbage-with-at-sign',
        'missing-message',
        'whitespace-only-message',
    ],
)
def test_report_dialog_submit_rejects_incomplete_input(
        monkeypatch, name, email, message):
    mock_warn = mock.MagicMock()
    monkeypatch.setattr(help_viewer.messagebox, 'showwarning', mock_warn)
    mock_open = mock.MagicMock()
    monkeypatch.setattr(help_viewer.webbrowser, 'open', mock_open)

    harness = _open_dialog(monkeypatch, 'bug')
    harness.name_var.get.return_value = name
    harness.email_var.get.return_value = email
    harness.message.get.return_value = message

    harness.submit()

    mock_warn.assert_called_once()
    mock_open.assert_not_called()
    harness.dialog.destroy.assert_not_called()


@pytest.mark.parametrize(
    ('kind', 'field_id', 'template'),
    [
        ('bug', 'description', 'bug_report.yml'),
        ('feature', 'problem', 'feature_request.yml'),
    ],
    ids=['bug', 'feature'],
)
def test_report_dialog_submit_valid_input_opens_browser_and_closes(
        monkeypatch, kind, field_id, template):
    mock_open = mock.MagicMock(return_value=True)
    monkeypatch.setattr(help_viewer.webbrowser, 'open', mock_open)
    mock_warn = mock.MagicMock()
    monkeypatch.setattr(help_viewer.messagebox, 'showwarning', mock_warn)

    harness = _open_dialog(monkeypatch, kind)
    harness.name_var.get.return_value = 'Jane Doe'
    harness.email_var.get.return_value = 'jane@example.com'
    harness.message.get.return_value = 'Something is broken'

    harness.submit()

    mock_warn.assert_not_called()
    mock_open.assert_called_once()
    (url,), _kwargs = mock_open.call_args
    qs = parse_qs(urlparse(url).query)
    assert qs['template'] == [template]
    assert qs['contact'] == ['Jane Doe <jane@example.com>']
    assert qs[field_id] == ['Something is broken']
    harness.dialog.destroy.assert_called_once()


def test_report_dialog_submit_webbrowser_error_keeps_dialog_open(monkeypatch):
    monkeypatch.setattr(
        help_viewer.webbrowser, 'open',
        mock.MagicMock(side_effect=webbrowser.Error('boom')),
    )
    mock_error = mock.MagicMock()
    monkeypatch.setattr(help_viewer.messagebox, 'showerror', mock_error)

    harness = _open_dialog(monkeypatch, 'bug')
    harness.name_var.get.return_value = 'Jane'
    harness.email_var.get.return_value = 'jane@example.com'
    harness.message.get.return_value = 'It crashed'

    harness.submit()

    mock_error.assert_called_once()
    assert 'boom' in mock_error.call_args[0][1]
    harness.dialog.destroy.assert_not_called()


def test_report_dialog_submit_oserror_keeps_dialog_open(monkeypatch):
    """webbrowser.open() can raise a plain OSError rather than
    webbrowser.Error (see test_open_help_oserror_shows_error_message);
    _report_dialog's submit handler must catch that too."""
    monkeypatch.setattr(
        help_viewer.webbrowser, 'open',
        mock.MagicMock(side_effect=OSError('no such file or directory')),
    )
    mock_error = mock.MagicMock()
    monkeypatch.setattr(help_viewer.messagebox, 'showerror', mock_error)

    harness = _open_dialog(monkeypatch, 'bug')
    harness.name_var.get.return_value = 'Jane'
    harness.email_var.get.return_value = 'jane@example.com'
    harness.message.get.return_value = 'It crashed'

    harness.submit()

    mock_error.assert_called_once()
    assert 'no such file or directory' in mock_error.call_args[0][1]
    harness.dialog.destroy.assert_not_called()


def test_report_dialog_submit_message_too_long_shows_warning_and_keeps_dialog_open(
        monkeypatch):
    mock_warn = mock.MagicMock()
    monkeypatch.setattr(help_viewer.messagebox, 'showwarning', mock_warn)
    mock_open = mock.MagicMock()
    monkeypatch.setattr(help_viewer.webbrowser, 'open', mock_open)

    harness = _open_dialog(monkeypatch, 'bug')
    harness.name_var.get.return_value = 'Jane'
    harness.email_var.get.return_value = 'jane@example.com'
    harness.message.get.return_value = 'x' * help_viewer._MAX_ISSUE_URL_LENGTH

    harness.submit()

    mock_warn.assert_called_once()
    assert mock_warn.call_args[0][0] == 'Message Too Long'
    mock_open.assert_not_called()
    harness.dialog.destroy.assert_not_called()


def test_report_dialog_submit_browser_open_returns_false_keeps_dialog_open(monkeypatch):
    monkeypatch.setattr(
        help_viewer.webbrowser, 'open', mock.MagicMock(return_value=False))
    mock_error = mock.MagicMock()
    monkeypatch.setattr(help_viewer.messagebox, 'showerror', mock_error)

    harness = _open_dialog(monkeypatch, 'feature')
    harness.name_var.get.return_value = 'Jane'
    harness.email_var.get.return_value = 'jane@example.com'
    harness.message.get.return_value = 'A new idea'

    harness.submit()

    mock_error.assert_called_once_with(
        'Browser Error', 'Could not open a web browser.', parent=harness.dialog)
    harness.dialog.destroy.assert_not_called()


@pytest.mark.parametrize(
    ('func_name', 'kind'),
    [('report_bug', 'bug'), ('suggest_feature', 'feature')],
    ids=['report_bug', 'suggest_feature'],
)
def test_report_dialog_wrappers_delegate_with_correct_kind(
        monkeypatch, func_name, kind):
    calls = []
    monkeypatch.setattr(
        help_viewer, '_report_dialog',
        lambda parent, k: calls.append((parent, k)),
    )
    sentinel_parent = object()

    getattr(help_viewer, func_name)(sentinel_parent)

    assert calls == [(sentinel_parent, kind)]


def test_show_about_displays_app_version(monkeypatch):
    """The About dialog must surface help_viewer._APP_VERSION (sourced from
    version.__version__) so a user can answer bug_report.yml's "app
    version" environment field without guessing."""
    label_texts = []

    def _fake_label(*_args, **kwargs):
        if 'text' in kwargs:
            label_texts.append(kwargs['text'])
        return mock.MagicMock()

    monkeypatch.setattr(help_viewer.tk, 'Toplevel', lambda *_a, **_k: mock.MagicMock())
    monkeypatch.setattr(help_viewer.ttk, 'Frame', lambda *_a, **_k: mock.MagicMock())
    monkeypatch.setattr(help_viewer.ttk, 'Label', _fake_label)
    monkeypatch.setattr(help_viewer.tk, 'Label', _fake_label)
    monkeypatch.setattr(help_viewer.ttk, 'Button', lambda *_a, **_k: mock.MagicMock())

    help_viewer.show_about(None)

    assert f'Version {help_viewer._APP_VERSION}' in label_texts
