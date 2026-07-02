"""Regression tests for GitHub issue form templates."""
import re
from pathlib import Path

from views.help_viewer import _KIND_CONFIG

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


def test_field_id_by_kind_matches_template_field_ids():
    for kind, config in _KIND_CONFIG.items():
        content = (TEMPLATE_DIR / config.template).read_text()
        assert f'id: {config.field_id}' in content, (
            f'{kind}: expected field id {config.field_id!r} in {config.template}'
        )


def test_field_id_by_kind_targets_a_textarea_field():
    """`_build_issue_url` prefills `config.field_id` via a URL query param,
    which only works for free-text `textarea`/`input` fields on GitHub's
    issue form -- not `dropdown`/`checkboxes`, whose prefill requires an
    exact match against a fixed set of option labels. If a template's
    field type is changed without updating views/help_viewer.py, the
    substring check above still passes while prefill silently breaks;
    this test catches that by asserting the field's declared `type:`."""
    field_type_re = re.compile(r'-\s*type:\s*(\w+)\s*\n\s*id:\s*(\w+)')
    for kind, config in _KIND_CONFIG.items():
        content = (TEMPLATE_DIR / config.template).read_text()
        field_types = dict(
            (field_id, field_type)
            for field_type, field_id in field_type_re.findall(content)
        )
        assert field_types.get(config.field_id) == 'textarea', (
            f'{kind}: expected {config.field_id!r} to be a textarea field '
            f'in {config.template}, got {field_types.get(config.field_id)!r}'
        )
