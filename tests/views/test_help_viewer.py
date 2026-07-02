"""Tests for the pure URL-building helper behind the report dialogs."""
from urllib.parse import parse_qs, urlparse

import pytest

from views.help_viewer import _build_issue_url


def test_build_issue_url_bug():
    url = _build_issue_url(
        'bug', 'Jane Doe', 'jane@example.com', 'It crashes on save')
    parsed = urlparse(url)
    assert parsed.scheme == 'https'
    assert parsed.netloc == 'github.com'
    assert parsed.path == '/david-wies/time-clock/issues/new'
    qs = parse_qs(parsed.query)
    assert qs['template'] == ['bug_report.yml']
    assert qs['contact'] == ['Jane Doe <jane@example.com>']
    assert qs['description'] == ['It crashes on save']


def test_build_issue_url_feature():
    url = _build_issue_url(
        'feature', 'John Smith', 'john@example.com', 'Add dark mode')
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    assert qs['template'] == ['feature_request.yml']
    assert qs['contact'] == ['John Smith <john@example.com>']
    assert qs['problem'] == ['Add dark mode']


def test_build_issue_url_encodes_special_characters():
    url = _build_issue_url(
        'bug', 'A & B', 'a+b@example.com', 'Line one\nLine two & more')
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    assert qs['contact'] == ['A & B <a+b@example.com>']
    assert qs['description'] == ['Line one\nLine two & more']


@pytest.mark.parametrize(
    'message',
    [
        '50% done & tested',
        'price=$5 #urgent for v2?',
        'café naïve résumé ☃',
        'multi\nline\nmessage\nwith\nnewlines',
        '   ',
        '',
    ],
    ids=[
        'percent-ampersand',
        'equals-hash-question',
        'unicode',
        'newlines',
        'whitespace-only',
        'empty',
    ],
)
def test_build_issue_url_round_trips_message_body_unmodified(message):
    """_build_issue_url is a pure formatter: it must not trim or otherwise
    alter the message body. Required-field validation (rejecting empty or
    whitespace-only input) is the dialog's job, tested separately in
    test_help_viewer_dialogs.py against the real _on_submit handler."""
    url = _build_issue_url('bug', 'Jane Doe', 'jane@example.com', message)
    qs = parse_qs(urlparse(url).query, keep_blank_values=True)
    assert qs['description'] == [message]


def test_build_issue_url_unicode_name_and_email_round_trip():
    url = _build_issue_url(
        'feature', 'Élodie Dubois', 'elodie@éxample.com', 'Add émoji support')
    qs = parse_qs(urlparse(url).query)
    assert qs['contact'] == ['Élodie Dubois <elodie@éxample.com>']
    assert qs['problem'] == ['Add émoji support']


def test_build_issue_url_unknown_kind_raises_key_error():
    """kind dispatches through _TEMPLATE_BY_KIND/_FIELD_ID_BY_KIND; an
    unrecognized kind is a programming error in the caller, not user
    input, so it should fail loudly rather than silently defaulting."""
    with pytest.raises(KeyError):
        _build_issue_url('typo', 'Jane', 'jane@example.com', 'message')
