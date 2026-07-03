"""Unit tests for SettingsManager: DEFAULTS lookup, DB persistence, and type round-trips."""

import pytest

from settings import SettingsManager


# settings_manager fixture provided by tests/conftest.py (fresh in-memory DB each test)


# ─────────────── DEFAULTS fallback behaviour ─────────────────────────────────

def test_get_key_in_defaults_returns_defaults_value(settings_manager):
    # "theme" is in SettingsManager.DEFAULTS as "system"; DB has no entry for it.
    assert settings_manager.get("theme") == "system"


def test_get_key_in_defaults_ignores_caller_supplied_default(settings_manager):
    # DEFAULTS value takes precedence over the caller's explicit fallback.
    assert settings_manager.get("theme", "caller-value") == "system"


def test_get_default_work_type_from_defaults(settings_manager):
    assert settings_manager.get("default_work_type") == "remote"


def test_get_overtime_rate_from_defaults(settings_manager):
    assert settings_manager.get("overtime_rate") == pytest.approx(1.0)


def test_get_minimize_to_tray_from_defaults(settings_manager):
    assert settings_manager.get("minimize_to_tray") is False


# ─────────────── Missing-key behaviour ───────────────────────────────────────

def test_get_unknown_key_uses_caller_default(settings_manager):
    # Key is absent from both DEFAULTS and DB; caller's default is returned.
    assert settings_manager.get("no_such_key", "fallback") == "fallback"


def test_get_unknown_key_returns_none_when_no_caller_default(settings_manager):
    # No caller default means Python's default of None is returned.
    assert settings_manager.get("no_such_key") is None


# ─────────────── DB value overrides DEFAULTS ─────────────────────────────────

def test_db_value_overrides_defaults(settings_manager):
    # After set(), the stored value must shadow the DEFAULTS entry.
    settings_manager.set("theme", "dark")
    assert settings_manager.get("theme") == "dark"


def test_db_value_overrides_defaults_bool(settings_manager):
    settings_manager.set("minimize_to_tray", True)
    assert settings_manager.get("minimize_to_tray") is True


# ─────────────── JSON type round-trips ───────────────────────────────────────

def test_set_get_round_trip_string(settings_manager):
    settings_manager.set("last_country_holiday", "Germany")
    assert settings_manager.get("last_country_holiday") == "Germany"


def test_set_get_round_trip_int(settings_manager):
    settings_manager.set("custom_max_items", 99)
    assert settings_manager.get("custom_max_items") == 99


def test_set_get_round_trip_float(settings_manager):
    settings_manager.set("overtime_rate", 1.5)
    assert settings_manager.get("overtime_rate") == pytest.approx(1.5)


def test_set_get_round_trip_bool_false(settings_manager):
    settings_manager.set("custom_flag", False)
    assert settings_manager.get("custom_flag") is False


def test_set_get_round_trip_list(settings_manager):
    offices = ["Main Office", "Branch A", "Remote"]
    settings_manager.set("offices", offices)
    assert settings_manager.get("offices") == offices


def test_set_get_round_trip_dict(settings_manager):
    targets = {"0": 8.0, "4": 6.0, "5": 0.0}
    settings_manager.set("work_day_targets", targets)
    assert settings_manager.get("work_day_targets") == targets


def test_set_get_round_trip_empty_list(settings_manager):
    settings_manager.set("break_presets", [])
    assert settings_manager.get("break_presets") == []


# ─────────────── Overwrite and isolation ─────────────────────────────────────

def test_set_overwrites_previous_value(settings_manager):
    settings_manager.set("view_mode", "week")
    assert settings_manager.get("view_mode") == "week"
    settings_manager.set("view_mode", "month")
    assert settings_manager.get("view_mode") == "month"


def test_multiple_keys_are_stored_independently(settings_manager):
    settings_manager.set("key_alpha", "a")
    settings_manager.set("key_beta", "b")
    assert settings_manager.get("key_alpha") == "a"
    assert settings_manager.get("key_beta") == "b"


def test_changing_one_key_does_not_affect_another(settings_manager):
    settings_manager.set("key_x", "original")
    settings_manager.set("key_y", "unchanged")
    settings_manager.set("key_x", "updated")
    assert settings_manager.get("key_y") == "unchanged"


# ─────────────── get() returns independent copies (no shared mutable state) ──

def test_mutating_returned_default_list_does_not_corrupt_shared_default(settings_manager):
    # Regression test: SettingsManager.DEFAULTS["offices"] is a class-level
    # mutable list. get() must never hand back a reference to it — otherwise
    # a caller appending to the returned list corrupts the default for the
    # rest of the process's lifetime.
    offices = settings_manager.get("offices")
    offices.append("Injected Office")

    assert settings_manager.get("offices") == ["Office A", "Office B", "Office C"]
    assert SettingsManager.DEFAULTS["offices"] == ["Office A", "Office B", "Office C"]


def test_mutating_returned_default_break_presets_does_not_corrupt_shared_default(settings_manager):
    presets = settings_manager.get("break_presets")
    presets.clear()

    assert settings_manager.get("break_presets") == [15, 30, 45, 60]
    assert SettingsManager.DEFAULTS["break_presets"] == [15, 30, 45, 60]


def test_two_calls_to_get_return_independent_list_objects(settings_manager):
    first = settings_manager.get("offices")
    second = settings_manager.get("offices")
    assert first == second
    assert first is not second


def test_mutating_caller_supplied_mutable_default_does_not_leak(settings_manager):
    fallback = {"a": 1}
    result = settings_manager.get("no_such_key", fallback)
    result["a"] = 999
    assert fallback == {"a": 1}
