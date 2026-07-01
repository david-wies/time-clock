"""Regression tests for GitHub issue form templates."""
from pathlib import Path

TEMPLATE_DIR = Path(__file__).parent.parent / '.github' / 'ISSUE_TEMPLATE'


def test_bug_report_template_has_required_contact_field():
    content = (TEMPLATE_DIR / 'bug_report.yml').read_text()
    assert 'id: contact' in content
    assert 'required: true' in content
    assert content.index('id: contact') < content.index('id: description')


def test_feature_request_template_has_required_contact_field():
    content = (TEMPLATE_DIR / 'feature_request.yml').read_text()
    assert 'id: contact' in content
    assert content.index('id: contact') < content.index('id: problem')
