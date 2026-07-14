"""Tests for theme.style.resolve_theme_mode (pure, no Tk needed)."""

from theme.style import COLORS, resolve_theme_mode


def test_resolve_theme_mode_passes_through_known_modes() -> None:
    """Explicit "light"/"dark" modes pass through unchanged."""
    assert resolve_theme_mode("light") == "light"
    assert resolve_theme_mode("dark") == "dark"


def test_resolve_theme_mode_defaults_system_to_light() -> None:
    """The "system" mode resolves to "light"."""
    assert resolve_theme_mode("system") == "light"


def test_resolve_theme_mode_defaults_none_to_light() -> None:
    """None resolves to "light"."""
    assert resolve_theme_mode(None) == "light"


def test_resolve_theme_mode_defaults_unknown_value_to_light() -> None:
    """An unrecognized mode string resolves to "light"."""
    assert resolve_theme_mode("neon") == "light"


def test_resolve_theme_mode_result_is_always_a_valid_colors_key() -> None:
    """Every resolved mode is a valid key into the COLORS table."""
    for mode in ("light", "dark", "system", None, "bogus"):
        assert resolve_theme_mode(mode) in COLORS
