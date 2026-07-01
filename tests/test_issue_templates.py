"""Regression tests for GitHub issue form templates."""
from pathlib import Path

TEMPLATE_DIR = Path(__file__).parent.parent / '.github' / 'ISSUE_TEMPLATE'


def test_bug_report_template_has_required_contact_field():
    content = (TEMPLATE_DIR / 'bug_report.yml').read_text()
    assert 'id: contact' in content
    contact_start = content.index('id: contact')
    description_start = content.index('id: description')
    assert contact_start < description_start
    contact_block = content[contact_start:description_start]
    assert 'required: true' in contact_block


def test_feature_request_template_has_required_contact_field():
    content = (TEMPLATE_DIR / 'feature_request.yml').read_text()
    assert 'id: contact' in content
    contact_start = content.index('id: contact')
    problem_start = content.index('id: problem')
    assert contact_start < problem_start
    contact_block = content[contact_start:problem_start]
    assert 'required: true' in contact_block
