# Time Clock

A desktop time-tracking application built with Python and tkinter. Tracks daily work hours, vacation, and sick leave — with Hebrew-date support, a system-tray icon, and offline PDF reports.

![Python](https://img.shields.io/badge/python-3.10%2B-blue) ![License](https://img.shields.io/badge/license-MIT-green)

---

## Features

- **Time Clock** — Clock in/out, manual records, overnight-shift support, week/month views with running balance
- **Vacation** — Annual allowance, carry-over, five leave types (annual, public holiday, special, unpaid, carry-over), balance warning on over-draw
- **Sickness** — Hours-to-day conversion, per-year allowance, balance tracking
- **Miliuim** — Reserve-duty periods tracked as date ranges, with optional document attachment per period
- **Settings** — Per-day work targets, break presets, office list, overtime rate, holiday auto-import (34 countries), light/dark/system theme
- **Export** — CSV, Excel (`pandas`/`openpyxl`), PDF (`reportlab`) for each tab
- **PDF Reports** — Monthly, quarterly, yearly summaries with overtime and absence breakdown
- **System Tray** — Quick clock-in/out from tray; minimize-to-tray option
- **Hebrew dates** — Full Hebrew calendar column when `hdate` is installed

---

## Requirements

- Python 3.10+
- See `requirements.txt` for all dependencies

---

## Setup

```bash
# Clone
git clone <repo-url>
cd "Time Clock"

# Create virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

---

## Running

```bash
python main.py
```

---

## Project Structure

```
Time Clock/
├── main.py                  # Entry point — wires all layers together
├── settings.py              # SettingsManager (DB-backed key/value store)
├── requirements.txt
│
├── domain/                  # Pure data types and enums (no I/O)
│   ├── enums.py             # WorkType, VacationType, Weekday
│   └── types.py             # TimeRecord, VacationRecord, SicknessRecord, Result
│
├── core/                    # Business logic (no GUI, no DB)
│   ├── events.py            # Synchronous EventBus
│   ├── timeutil.py          # Date/time utilities, duration arithmetic
│   ├── hebrew_date.py       # Hebrew calendar label via hdate
│   ├── balance.py           # Overtime & period balance engine
│   └── report.py            # Pure data-assembly for PDF reports
│
├── db/
│   └── database.py          # SQLite schema, migrations, connection factory
│
├── models/                  # Data access layer (SQLite CRUD + queries)
│   ├── time_clock_model.py
│   ├── vacation_model.py
│   ├── sickness_model.py
│   └── miliuim_model.py
│
├── controllers/             # Validation + orchestration (no GUI)
│   ├── time_clock_controller.py
│   ├── vacation_controller.py
│   ├── sickness_controller.py
│   └── miliuim_controller.py
│
├── views/                   # All tkinter UI
│   ├── main_window.py       # Root window, notebook, menu bar, status bar
│   ├── tray.py              # System-tray icon (pystray)
│   ├── time_clock_tab.py
│   ├── vacation_tab.py
│   ├── sickness_tab.py
│   ├── miliuim_tab.py
│   ├── time_record_dialog.py
│   ├── vacation_record_dialog.py
│   ├── sick_record_dialog.py
│   ├── miliuim_record_dialog.py
│   ├── carry_over_dialog.py
│   ├── document_attachment.py
│   ├── settings_dialog.py
│   ├── export_dialog.py
│   ├── report_dialog.py
│   ├── date_picker.py
│   └── help_viewer.py
│
├── theme/
│   └── style.py             # sv-ttk theme + named ttk styles + colour tokens
│
├── help/
│   └── index.html           # Offline HTML help (opened in browser via F1)
│
├── resources/
│   └── time-clock.png       # App / tray icon
│
└── tests/
    ├── conftest.py           # In-memory DB fixture, fixed-clock fixture
    ├── test_integration.py
    ├── core/
    ├── models/
    └── controllers/
```

### Architecture

```
Views → Controllers → Models → SQLite
          ↕ bus.publish(Event.*)
```

- **No raw dicts cross layer boundaries** — use typed dataclasses from `domain/types.py`
- **Controllers return `Result(ok, errors)`** — never raise for expected validation failures
- **EventBus is synchronous** — models publish after every successful mutation; views subscribe and refresh

---

## Testing

```bash
pytest tests/ -v --cov=domain --cov=core --cov=models --cov=controllers
```

Type-check:

```bash
mypy --strict domain/ core/ controllers/
```

---

## Data Storage

All data is stored in a local SQLite database:

| OS      | Path |
|---------|------|
| Windows | `%APPDATA%\Time Clock\time_clock.db` |
| macOS   | `~/Library/Application Support/Time Clock/time_clock.db` |
| Linux   | `~/.local/share/time-clock/time_clock.db` |

Settings are stored in the `app_config` table as JSON-serialized key/value pairs.

---

## Key Behaviours

- **Time fields are local wall-clock** (`HH:MM`). UTC is used only for `created_at`/`updated_at` audit columns.
- **Overnight shifts** (`end < start`) are fully supported — duration computed as `(1440 − start_mins) + end_mins − break`.
- **Holiday import** adds public holidays as Vacation tab records (type: Public Holiday, 0 h — visible for reference, no quota impact).
- **Vacation carry-over** is capped per the per-year `max_carry_over` setting and logged in `carry_over_log`.
- **Tray thread safety** — all pystray callbacks marshal to the tkinter main thread via `root.after(0, fn)`.

---

## Feedback

Found a bug or have a feature idea? Use **Help → Report a Bug** or **Help → Suggest a Feature** in the app —
it opens a prefilled GitHub issue in your browser for you to review and submit. Or file one directly at
[github.com/david-wies/time-clock/issues](https://github.com/david-wies/time-clock/issues).
