"""Tests for the pure URL-building helper behind the report dialogs."""
from urllib.parse import parse_qs, urlparse

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
