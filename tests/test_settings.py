"""Unit tests for SettingsManager: DEFAULTS lookup, DB persistence, and type
round-trips.
"""

import logging
import sqlite3

import pytest

from settings import SettingsManager

# settings_manager fixture provided by tests/conftest.py (fresh in-memory DB each test)


# ─────────────── DEFAULTS fallback behaviour ─────────────────────────────────


def test_get_key_in_defaults_returns_defaults_value(settings_manager):
    """A key present in DEFAULTS but absent from the DB returns the DEFAULTS value."""
    # "theme" is in SettingsManager.DEFAULTS as "system"; DB has no entry for it.
    assert settings_manager.get("theme") == "system"


def test_get_key_in_defaults_ignores_caller_supplied_default(settings_manager):
    """A DEFAULTS value takes precedence over a caller-supplied fallback."""
    # DEFAULTS value takes precedence over the caller's explicit fallback.
    assert settings_manager.get("theme", "caller-value") == "system"


def test_get_default_work_type_from_defaults(settings_manager):
    """The default_work_type default is "remote"."""
    assert settings_manager.get("default_work_type") == "remote"


def test_get_overtime_rate_from_defaults(settings_manager):
    """The overtime_rate default is 1.0."""
    assert settings_manager.get("overtime_rate") == pytest.approx(1.0)


def test_get_minimize_to_tray_from_defaults(settings_manager):
    """The minimize_to_tray default is False."""
    assert settings_manager.get("minimize_to_tray") is False


# ─────────────── Missing-key behaviour ───────────────────────────────────────


def test_get_unknown_key_uses_caller_default(settings_manager):
    """A key absent from both DEFAULTS and DB returns the caller's default."""
    # Key is absent from both DEFAULTS and DB; caller's default is returned.
    assert settings_manager.get("no_such_key", "fallback") == "fallback"


def test_get_unknown_key_returns_none_when_no_caller_default(settings_manager):
    """An unknown key with no caller default returns None."""
    # No caller default means Python's default of None is returned.
    assert settings_manager.get("no_such_key") is None


# ─────────────── DB value overrides DEFAULTS ─────────────────────────────────


def test_db_value_overrides_defaults(settings_manager):
    """A stored DB value shadows the DEFAULTS entry for the same key."""
    # After set(), the stored value must shadow the DEFAULTS entry.
    settings_manager.set("theme", "dark")
    assert settings_manager.get("theme") == "dark"


def test_db_value_overrides_defaults_bool(settings_manager):
    """A stored bool value shadows the DEFAULTS entry."""
    settings_manager.set("minimize_to_tray", True)
    assert settings_manager.get("minimize_to_tray") is True


# ─────────────── JSON type round-trips ───────────────────────────────────────


def test_set_get_round_trip_string(settings_manager):
    """A string value survives a set()/get() round-trip."""
    settings_manager.set("last_country_holiday", "Germany")
    assert settings_manager.get("last_country_holiday") == "Germany"


def test_set_get_round_trip_int(settings_manager):
    """An int value survives a set()/get() round-trip."""
    settings_manager.set("custom_max_items", 99)
    assert settings_manager.get("custom_max_items") == 99


def test_set_get_round_trip_float(settings_manager):
    """A float value survives a set()/get() round-trip."""
    settings_manager.set("overtime_rate", 1.5)
    assert settings_manager.get("overtime_rate") == pytest.approx(1.5)


def test_set_get_round_trip_bool_false(settings_manager):
    """A False bool value survives a set()/get() round-trip."""
    settings_manager.set("custom_flag", False)
    assert settings_manager.get("custom_flag") is False


def test_set_get_round_trip_list(settings_manager):
    """A list value survives a set()/get() round-trip."""
    offices = ["Main Office", "Branch A", "Remote"]
    settings_manager.set("offices", offices)
    assert settings_manager.get("offices") == offices


def test_set_get_round_trip_dict(settings_manager):
    """A dict value survives a set()/get() round-trip."""
    targets = {"0": 8.0, "4": 6.0, "5": 0.0}
    settings_manager.set("work_day_targets", targets)
    assert settings_manager.get("work_day_targets") == targets


def test_set_get_round_trip_empty_list(settings_manager):
    """An empty list value survives a set()/get() round-trip."""
    settings_manager.set("break_presets", [])
    assert settings_manager.get("break_presets") == []


# ─────────────── Overwrite and isolation ─────────────────────────────────────


def test_set_overwrites_previous_value(settings_manager):
    """A second set() overwrites the previously stored value for a key."""
    settings_manager.set("view_mode", "week")
    assert settings_manager.get("view_mode") == "week"
    settings_manager.set("view_mode", "month")
    assert settings_manager.get("view_mode") == "month"


def test_multiple_keys_are_stored_independently(settings_manager):
    """Distinct keys are stored and retrieved independently."""
    settings_manager.set("key_alpha", "a")
    settings_manager.set("key_beta", "b")
    assert settings_manager.get("key_alpha") == "a"
    assert settings_manager.get("key_beta") == "b"


def test_changing_one_key_does_not_affect_another(settings_manager):
    """Overwriting one key leaves other keys unchanged."""
    settings_manager.set("key_x", "original")
    settings_manager.set("key_y", "unchanged")
    settings_manager.set("key_x", "updated")
    assert settings_manager.get("key_y") == "unchanged"


# ─────────────── get() returns independent copies (no shared mutable state) ──


def test_mutating_returned_default_list_does_not_corrupt_shared_default(
    settings_manager,
):
    """Mutating a returned default list must not corrupt the shared DEFAULTS."""
    # Regression test: SettingsManager.DEFAULTS["offices"] is a class-level
    # mutable list. get() must never hand back a reference to it — otherwise
    # a caller appending to the returned list corrupts the default for the
    # rest of the process's lifetime.
    offices = settings_manager.get("offices")
    offices.append("Injected Office")

    assert settings_manager.get("offices") == ["Office A", "Office B", "Office C"]
    assert SettingsManager.DEFAULTS["offices"] == ["Office A", "Office B", "Office C"]


def test_mutating_returned_default_break_presets_does_not_corrupt_shared_default(
    settings_manager,
):
    """Mutating a returned default break_presets list must not corrupt DEFAULTS."""
    presets = settings_manager.get("break_presets")
    presets.clear()

    assert settings_manager.get("break_presets") == [15, 30, 45, 60]
    assert SettingsManager.DEFAULTS["break_presets"] == [15, 30, 45, 60]


def test_two_calls_to_get_return_independent_list_objects(settings_manager):
    """Two get() calls for a list default return equal but distinct objects."""
    first = settings_manager.get("offices")
    second = settings_manager.get("offices")
    assert first == second
    assert first is not second


def test_mutating_caller_supplied_mutable_default_does_not_leak(settings_manager):
    """Mutating the get() result must not mutate the caller's fallback object."""
    fallback = {"a": 1}
    result = settings_manager.get("no_such_key", fallback)
    result["a"] = 999
    assert fallback == {"a": 1}


# ─────────────── Corrupted-JSON and DB-error fallback branches ──────────────
# get() wraps its DB read in try/except for json.JSONDecodeError and
# sqlite3.Error, logging a warning and falling back to the same
# DEFAULTS-then-caller-default chain used for a missing key. Neither branch
# is exercised by set()/get() round-trips above (set() always writes valid
# JSON, and a healthy in-memory DB never raises sqlite3.Error), so both are
# triggered here directly: (a) a malformed JSON value written straight into
# app_config, bypassing set(); (b) a monkeypatched connection.cursor() that
# raises sqlite3.Error to simulate a DB read failure.


def _write_raw_config_value(
    settings_manager: SettingsManager, key: str, raw_value: str
) -> None:
    """Inserts a raw (not necessarily valid-JSON) string directly into
    app_config, bypassing SettingsManager.set() — which always serializes
    through json.dumps() and could never produce malformed JSON itself."""
    conn = settings_manager.db.get_connection()
    try:
        with conn:
            conn.execute(
                "INSERT INTO app_config (key, value) VALUES (?, ?);",
                (key, raw_value),
            )
    finally:
        conn.close()


def test_get_corrupted_json_for_defaults_key_falls_back_to_defaults_value(
    settings_manager, caplog: pytest.LogCaptureFixture
):
    """ "theme" is a DEFAULTS key ("system") — corrupted JSON in the DB must
    fall back to the DEFAULTS value, not the caller-supplied default (same
    precedence as the missing-key case)."""
    _write_raw_config_value(settings_manager, "theme", "{not valid json")

    with caplog.at_level(logging.WARNING, logger="settings"):
        result = settings_manager.get("theme", "caller-value")

    assert result == "system"
    assert any(
        record.levelname == "WARNING" and "corrupted value" in record.message.lower()
        for record in caplog.records
    )


def test_get_corrupted_json_for_unknown_key_falls_back_to_caller_default(
    settings_manager, caplog: pytest.LogCaptureFixture
):
    """A key absent from DEFAULTS falls back to the caller-supplied default
    when its stored value is corrupted JSON."""
    _write_raw_config_value(settings_manager, "custom_key", "not json at all }")

    with caplog.at_level(logging.WARNING, logger="settings"):
        result = settings_manager.get("custom_key", "fallback-value")

    assert result == "fallback-value"
    assert any(record.levelname == "WARNING" for record in caplog.records)


def test_get_db_error_during_read_falls_back_to_default_and_logs(
    settings_manager, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    """A sqlite3.Error raised while reading app_config (e.g. a locked or
    corrupted database file) must be caught, logged, and produce the same
    graceful fallback as a missing key or corrupted value — not propagate
    and crash the caller."""
    conn = settings_manager.db.get_connection()

    def _boom():
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(conn, "cursor", _boom)

    with caplog.at_level(logging.WARNING, logger="settings"):
        result = settings_manager.get("no_such_key", "fallback-value")

    assert result == "fallback-value"
    assert any(
        record.levelname == "WARNING" and "db read failed" in record.message.lower()
        for record in caplog.records
    )


def test_get_db_error_for_defaults_key_falls_back_to_defaults_value(
    settings_manager, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    """Same DB-error path, but for a DEFAULTS key — DEFAULTS must still win
    over the caller-supplied default, exactly as in the missing-key case."""
    conn = settings_manager.db.get_connection()

    def _boom():
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(conn, "cursor", _boom)

    with caplog.at_level(logging.WARNING, logger="settings"):
        result = settings_manager.get("theme", "caller-value")

    assert result == "system"
