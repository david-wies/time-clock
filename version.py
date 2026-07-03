"""Single source of truth for the application's version string.

Surfaced in the About dialog (views/help_viewer.py) and used to prefill
the "app version" line of the bug-report dialog's GitHub issue body, so
neither has to hardcode or guess the current version independently.
"""

__version__ = "1.1.0"
