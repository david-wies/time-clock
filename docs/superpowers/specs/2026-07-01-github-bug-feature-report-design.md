# Design: In-app bug report / feature request → GitHub

Date: 2026-07-01

## Purpose

Let users file bug reports and feature requests against the GitHub repo
(`github.com/david-wies/time-clock`) without leaving the app to hunt down the
issue tracker or template. The repo already has issue form templates
(`.github/ISSUE_TEMPLATE/bug_report.yml`, `feature_request.yml`); the app has
no entry point to them beyond the generic GitHub link in the About dialog.

## UI entry points

`Help` menu (`views/main_window.py`), below `About`, separated:

```
Help
 ├─ Usage Guide
 ├─ About
 ├─ ───────────
 ├─ Report a Bug
 └─ Suggest a Feature
```

Each item opens its own modal dialog instance — no shared dialog/kind picker
visible to the user.

## Dialog

New function `views/help_viewer.py:_report_dialog(parent, kind)`, `kind` is
`"bug"` or `"feature"`. Two thin public wrappers, `report_bug(parent)` and
`suggest_feature(parent)`, each call `_report_dialog` with the right `kind`
and are what the Help menu binds to.

Fields:
- **Name** — `ttk.Entry`, required
- **Email** — `ttk.Entry`, required, must contain `@`
- **Message** — `tk.Text`, required, multi-line
  - maps to the `description` field for `kind="bug"`
  - maps to the `problem` field for `kind="feature"`

Submit validates all three; on failure shows inline error (reuse
`messagebox.showwarning`-style pattern already used in `open_help`), does not
close the dialog. On success, builds the GitHub URL and opens it, then closes
the dialog.

## URL construction

Pure, testable helper (no Tk dependency) in `views/help_viewer.py`:

```python
def _build_issue_url(kind: str, name: str, email: str, message: str) -> str:
    ...
```

- `template` = `bug_report.yml` or `feature_request.yml`
- `contact` = `f"{name} <{email}>"`
- primary field (`description` or `problem`) = `message`
- built with `urllib.parse.urlencode` against
  `https://github.com/david-wies/time-clock/issues/new`

Remaining template fields (`steps`, `expected`, `environment` for bugs;
`solution`, `alternatives` for features) are left for the user to fill on the
GitHub page — submission requires a GitHub account/login regardless, so full
automation isn't possible from a desktop app.

## Issue template changes

Both `.github/ISSUE_TEMPLATE/bug_report.yml` and `feature_request.yml` get a
new field inserted after the intro `markdown` block and before the existing
fields:

```yaml
  - type: input
    id: contact
    attributes:
      label: Your name and email
      description: So we can follow up if we have questions.
    validations:
      required: true
```

This also improves the templates for anyone filing directly on GitHub, not
just app users.

## Testing

- `tests/views/` exists but only covers pure-logic helpers on views (e.g.
  `test_report_dialog.py` tests `ReportDialog._collect_documents`, a non-Tk
  method — no Tk mainloop is started in that suite). `_build_issue_url` is a
  pure function extracted specifically so it follows the same pattern; add
  `tests/views/test_help_viewer.py` covering both `kind` values and
  URL-encoding of special characters (spaces, `&`, non-ASCII) in
  name/email/message.
- No test for the dialog widget itself or `webbrowser.open` — out of scope,
  consistent with the rest of the views layer.

## Out of scope

- No persistence of past reports, no local issue history.
- No GitHub API integration (auth, direct issue creation) — URL prefill +
  browser handoff only.
- No changes to `show_about`'s existing GitHub link.
