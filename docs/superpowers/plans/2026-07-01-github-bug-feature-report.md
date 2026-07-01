# GitHub Bug/Feature Report Dialogs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add "Report a Bug" and "Suggest a Feature" items to the app's Help menu, each opening a small dialog (name/email/message) that hands off to a prefilled GitHub issue page in the default browser.

**Architecture:** Two new GitHub issue-form fields (`contact`) on the existing templates, a pure URL-building helper in `views/help_viewer.py`, a Tk modal dialog reusing that helper, and two Help-menu entries in `views/main_window.py` wired to it. No controller/model/DB/EventBus involvement — this is a stateless UI → browser handoff, consistent with the existing `open_help`/`show_about` functions in the same file.

**Tech Stack:** Python 3, tkinter/ttk, `webbrowser` (stdlib), `urllib.parse` (stdlib), pytest.

## Global Constraints

- No raw dicts crossing layer boundaries — N/A here, this feature has no domain/model layer involvement.
- Imports at file header only — never inside functions or methods.
- No `try/except ImportError` guards — all deps already in the venv; `urllib.parse` and `webbrowser` are stdlib.
- Follow PEP 8 / PEP 257.
- Repo URL is `https://github.com/david-wies/time-clock` (already used in `views/help_viewer.py:show_about`) — reuse, don't hardcode a second time differently.

---

### Task 1: Add required `contact` field to GitHub issue templates

**Files:**
- Modify: `.github/ISSUE_TEMPLATE/bug_report.yml`
- Modify: `.github/ISSUE_TEMPLATE/feature_request.yml`
- Test: `tests/test_issue_templates.py`

**Interfaces:**
- Consumes: nothing (static YAML files).
- Produces: both templates now have a field with `id: contact`, positioned before the first existing field, `required: true`. Task 2's `_build_issue_url` relies on this field id existing in both templates.

- [ ] **Step 1: Write the failing test**

Create `tests/test_issue_templates.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_issue_templates.py -v`
Expected: FAIL — `id: contact` not found in either file.

- [ ] **Step 3: Edit the templates**

In `.github/ISSUE_TEMPLATE/bug_report.yml`, insert this block immediately after the `markdown` block and before the existing `description` field (i.e. right before the `  - type: textarea\n    id: description` line):

```yaml
  - type: input
    id: contact
    attributes:
      label: Your name and email
      description: So we can follow up if we have questions.
    validations:
      required: true

```

Resulting file should read (full contents):

```yaml
name: Bug Report
description: File a bug report
labels: ["bug"]
body:
  - type: markdown
    attributes:
      value: |
        Thanks for taking the time to file a bug report. Please fill out the fields below.

  - type: input
    id: contact
    attributes:
      label: Your name and email
      description: So we can follow up if we have questions.
    validations:
      required: true

  - type: textarea
    id: description
    attributes:
      label: Describe the bug
      description: A clear and concise description of what the bug is.
    validations:
      required: true

  - type: textarea
    id: steps
    attributes:
      label: Steps to reproduce
      description: How do you trigger this bug?
      placeholder: |
        1. Open the app
        2. Navigate to '...'
        3. Click '...'
        4. See error
    validations:
      required: true

  - type: textarea
    id: expected
    attributes:
      label: Expected behavior
      description: What did you expect to happen?
    validations:
      required: true

  - type: textarea
    id: environment
    attributes:
      label: Environment
      description: OS, Python version, and app version (e.g. v1.2.0)
      placeholder: |
        OS: Windows 11 / macOS 14 / Ubuntu 24.04
        Python: 3.12.x
        App version: v1.0.0
    validations:
      required: false
```

In `.github/ISSUE_TEMPLATE/feature_request.yml`, insert the same `contact` block immediately after the `markdown` block and before the existing `problem` field. Resulting file should read (full contents):

```yaml
name: Feature Request
description: Suggest a new feature or enhancement
labels: ["enhancement"]
body:
  - type: markdown
    attributes:
      value: |
        Thanks for suggesting a new feature! Please fill out the fields below.

  - type: input
    id: contact
    attributes:
      label: Your name and email
      description: So we can follow up if we have questions.
    validations:
      required: true

  - type: textarea
    id: problem
    attributes:
      label: Problem
      description: What problem does this feature solve? What are you trying to do?
    validations:
      required: true

  - type: textarea
    id: solution
    attributes:
      label: Proposed solution
      description: Describe the feature or behavior you'd like to see.
    validations:
      required: true

  - type: textarea
    id: alternatives
    attributes:
      label: Alternatives considered
      description: Any other solutions or workarounds you've considered?
    validations:
      required: false
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_issue_templates.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add .github/ISSUE_TEMPLATE/bug_report.yml .github/ISSUE_TEMPLATE/feature_request.yml tests/test_issue_templates.py
git commit -m "feat: add required contact field to issue templates"
```

---

### Task 2: `_build_issue_url` helper

**Files:**
- Modify: `views/help_viewer.py`
- Test: `tests/views/test_help_viewer.py`

**Interfaces:**
- Consumes: nothing new (stdlib `urllib.parse.urlencode` only).
- Produces: `_build_issue_url(kind: str, name: str, email: str, message: str) -> str`, where `kind` is `'bug'` or `'feature'`. Task 3's dialog calls this directly and passes the result to `webbrowser.open`.

- [ ] **Step 1: Write the failing test**

Create `tests/views/test_help_viewer.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/views/test_help_viewer.py -v`
Expected: FAIL with `ImportError: cannot import name '_build_issue_url'`

- [ ] **Step 3: Write minimal implementation**

In `views/help_viewer.py`, add `from urllib.parse import urlencode` to the imports at the top of the file (alongside the existing `import webbrowser` etc.), and add below the existing `import` block, before `open_help`:

```python
_REPO_URL = 'https://github.com/david-wies/time-clock'

_TEMPLATE_BY_KIND = {
    'bug': 'bug_report.yml',
    'feature': 'feature_request.yml',
}

_FIELD_ID_BY_KIND = {
    'bug': 'description',
    'feature': 'problem',
}


def _build_issue_url(kind: str, name: str, email: str, message: str) -> str:
    """Builds a GitHub new-issue URL prefilled from the report dialog."""
    template = _TEMPLATE_BY_KIND[kind]
    field_id = _FIELD_ID_BY_KIND[kind]
    params = {
        'template': template,
        'contact': f'{name} <{email}>',
        field_id: message,
    }
    return f'{_REPO_URL}/issues/new?{urlencode(params)}'
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/views/test_help_viewer.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add views/help_viewer.py tests/views/test_help_viewer.py
git commit -m "feat: add GitHub issue URL builder for report dialogs"
```

---

### Task 3: Report dialog UI (`report_bug` / `suggest_feature`)

**Files:**
- Modify: `views/help_viewer.py`

**Interfaces:**
- Consumes: `_build_issue_url(kind, name, email, message) -> str` from Task 2.
- Produces: `report_bug(parent=None) -> None` and `suggest_feature(parent=None) -> None`. Task 4's Help menu binds directly to these two functions (same calling convention as the existing `show_about(parent)`).

No automated test for this step — the existing `show_about`/`open_help` dialogs in this same file have no Tk-level tests either (nothing in `tests/` drives a live Tk mainloop); this task follows that established pattern. Verify manually per Step 3 below.

- [ ] **Step 1: Add imports**

At the top of `views/help_viewer.py`, add `import tkinter as tk` is already present; add `from tkinter import StringVar` is unnecessary (`tk.StringVar` works). Confirm the file's import block now reads:

```python
"""Help viewer — opens documentation in the default browser."""
import webbrowser
from pathlib import Path
from tkinter import messagebox
from urllib.parse import urlencode
import tkinter as tk
from tkinter import ttk
```

- [ ] **Step 2: Implement the dialog and public wrappers**

Append to `views/help_viewer.py`, after `_build_issue_url` and before (or after) `show_about` — place it after `show_about`'s closing `return`:

```python
_DIALOG_TITLE_BY_KIND = {
    'bug': 'Report a Bug',
    'feature': 'Suggest a Feature',
}


def _report_dialog(parent, kind: str) -> None:
    """Opens a modal dialog collecting name/email/message, then opens
    a prefilled GitHub issue page in the default browser."""
    dialog = tk.Toplevel(parent)
    dialog.title(_DIALOG_TITLE_BY_KIND[kind])
    dialog.resizable(False, False)

    if parent is not None:
        dialog.transient(parent)

    container = ttk.Frame(dialog, padding=20)
    container.pack(fill='both', expand=True)

    ttk.Label(container, text='Name').grid(
        row=0, column=0, sticky='w', pady=(0, 4))
    name_var = tk.StringVar()
    ttk.Entry(container, textvariable=name_var, width=40).grid(
        row=1, column=0, sticky='ew', pady=(0, 10))

    ttk.Label(container, text='Email').grid(
        row=2, column=0, sticky='w', pady=(0, 4))
    email_var = tk.StringVar()
    ttk.Entry(container, textvariable=email_var, width=40).grid(
        row=3, column=0, sticky='ew', pady=(0, 10))

    ttk.Label(container, text='Message').grid(
        row=4, column=0, sticky='w', pady=(0, 4))
    message_text = tk.Text(container, width=40, height=8, wrap='word')
    message_text.grid(row=5, column=0, sticky='ew', pady=(0, 10))

    def _on_submit() -> None:
        name = name_var.get().strip()
        email = email_var.get().strip()
        message = message_text.get('1.0', 'end').strip()

        if not name or not email or '@' not in email or not message:
            messagebox.showwarning(
                'Missing Information',
                'Name, a valid email, and a message are all required.',
                parent=dialog,
            )
            return

        url = _build_issue_url(kind, name, email, message)
        webbrowser.open(url)
        dialog.destroy()

    button_row = ttk.Frame(container)
    button_row.grid(row=6, column=0, sticky='e')
    ttk.Button(button_row, text='Cancel', command=dialog.destroy).pack(
        side='right', padx=(6, 0))
    ttk.Button(button_row, text='Submit', command=_on_submit).pack(
        side='right')

    dialog.update_idletasks()
    if parent is not None:
        x = parent.winfo_rootx() + (parent.winfo_width() - dialog.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f'+{max(x, 0)}+{max(y, 0)}')

    dialog.grab_set()
    dialog.focus_set()
    dialog.bind('<Escape>', lambda e: dialog.destroy())
    dialog.wait_window()


def report_bug(parent=None) -> None:
    """Opens the bug-report dialog."""
    _report_dialog(parent, 'bug')


def suggest_feature(parent=None) -> None:
    """Opens the feature-request dialog."""
    _report_dialog(parent, 'feature')
```

- [ ] **Step 3: Manual verification**

Run: `python -c "import views.help_viewer"` — expected: no errors (import-only smoke check; confirms no syntax errors and all names resolve).

Then run the full suite to confirm nothing else broke:
Run: `pytest tests/ -v`
Expected: all existing tests still pass, plus Task 1/2's new tests.

- [ ] **Step 4: Commit**

```bash
git add views/help_viewer.py
git commit -m "feat: add report-a-bug and suggest-a-feature dialogs"
```

---

### Task 4: Wire Help menu

**Files:**
- Modify: `views/main_window.py:7` (import line), `views/main_window.py:81-85` (`_build_menu`, `help_menu` section)

**Interfaces:**
- Consumes: `report_bug(parent)` and `suggest_feature(parent)` from Task 3.
- Produces: nothing consumed by later tasks — this is the last task.

No new automated test — `views/main_window.py` has no existing test coverage (confirmed: no `tests/**/test_main_window.py`, no references to `MainWindow` under `tests/`), and menu wiring is exercised the same way `Settings`/`Reports`/`About` already are: manually. Verify per Step 3 below.

- [ ] **Step 1: Update the import**

In `views/main_window.py`, change line 7 from:

```python
from views.help_viewer import open_help, show_about
```

to:

```python
from views.help_viewer import open_help, report_bug, show_about, suggest_feature
```

- [ ] **Step 2: Add the menu items**

In `views/main_window.py`, in `_build_menu`, change:

```python
        help_menu = Menu(menubar, tearoff=0)
        help_menu.add_command(label="Usage Guide", command=open_help)
        help_menu.add_command(
            label="About", command=lambda: show_about(self.root))
        menubar.add_cascade(label="Help", menu=help_menu)
```

to:

```python
        help_menu = Menu(menubar, tearoff=0)
        help_menu.add_command(label="Usage Guide", command=open_help)
        help_menu.add_command(
            label="About", command=lambda: show_about(self.root))
        help_menu.add_separator()
        help_menu.add_command(
            label="Report a Bug", command=lambda: report_bug(self.root))
        help_menu.add_command(
            label="Suggest a Feature", command=lambda: suggest_feature(self.root))
        menubar.add_cascade(label="Help", menu=help_menu)
```

- [ ] **Step 3: Manual verification**

Run: `python main.py`, open the Help menu, confirm "Report a Bug" and "Suggest a Feature" appear below a separator under "About". Click "Report a Bug": dialog opens with Name/Email/Message fields. Leave a field blank and click Submit: warning dialog appears, report dialog stays open. Fill all three (e.g. `Test User` / `test@example.com` / `Sample message with special chars: & spaces`) and click Submit: default browser opens to a `github.com/david-wies/time-clock/issues/new?...` URL with `template=bug_report.yml` and the message/contact visible in the prefilled form; report dialog closes. Repeat for "Suggest a Feature", confirming `template=feature_request.yml` and the message lands in the "Problem" field.

Then run the full suite one more time:
Run: `pytest tests/ -v`
Expected: all tests pass (no regressions from the menu change).

- [ ] **Step 4: Commit**

```bash
git add views/main_window.py
git commit -m "feat: wire report-a-bug and suggest-a-feature into Help menu"
```
