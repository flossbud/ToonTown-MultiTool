"""Tests for chat handling mode (Simple/Advanced) feature.

Covers:
- Settings key default value.
- Pure-function effective-chat computation.
- MultitoonTab integration via get_chat_handling_mode.

See: docs/superpowers/specs/2026-05-26-chat-handling-mode-design.md
"""

from unittest.mock import MagicMock


def test_chat_handling_mode_constant_exists_and_is_string():
    """The settings key is a public constant in utils/settings_keys.py."""
    from utils.settings_keys import CHAT_HANDLING_MODE
    assert CHAT_HANDLING_MODE == "chat_handling_mode"


def test_chat_handling_mode_default_is_simple():
    """The CHAT_HANDLING_MODE_DEFAULT constant is 'simple'. Every read site
    imports this constant rather than duplicating the literal, so changing
    the default later is a one-line edit and call sites cannot drift."""
    from utils.settings_keys import CHAT_HANDLING_MODE_DEFAULT
    assert CHAT_HANDLING_MODE_DEFAULT == "simple"


# ── compute_effective_chat_enabled pure helper tests ─────────────────────


def test_effective_chat_simple_mode_all_default_keyset():
    """Every enabled toon is on set 0 -> all four broadcast in Simple mode."""
    from tabs.multitoon._tab import compute_effective_chat_enabled
    result = compute_effective_chat_enabled(
        mode="simple",
        raw_chat=[True, True, True, True],
        enabled_toons=[True, True, True, True],
        assignments=[0, 0, 0, 0],
    )
    assert result == [True, True, True, True]


def test_effective_chat_simple_mode_one_non_default_keyset():
    """A toon assigned to set 1 has chat OFF in Simple mode; others stay ON."""
    from tabs.multitoon._tab import compute_effective_chat_enabled
    result = compute_effective_chat_enabled(
        mode="simple",
        raw_chat=[True, True, True, True],
        enabled_toons=[True, True, True, True],
        assignments=[0, 1, 0, 0],
    )
    assert result == [True, False, True, True]


def test_effective_chat_simple_mode_disabled_toon():
    """A disabled toon has chat OFF regardless of keyset in Simple mode."""
    from tabs.multitoon._tab import compute_effective_chat_enabled
    result = compute_effective_chat_enabled(
        mode="simple",
        raw_chat=[True, True, True, True],
        enabled_toons=[True, False, True, True],
        assignments=[0, 0, 0, 0],
    )
    assert result == [True, False, True, True]


def test_effective_chat_advanced_mode_returns_raw():
    """In Advanced mode the helper returns the raw per-toon list unchanged,
    regardless of enabled_toons or assignments."""
    from tabs.multitoon._tab import compute_effective_chat_enabled
    result = compute_effective_chat_enabled(
        mode="advanced",
        raw_chat=[True, False, True, False],
        enabled_toons=[True, True, True, True],
        assignments=[1, 1, 1, 1],
    )
    assert result == [True, False, True, False]


def test_effective_chat_simple_mode_short_assignments_list():
    """Defensive: assignments shorter than enabled_toons treats missing
    indices as not-set-0 (chat off)."""
    from tabs.multitoon._tab import compute_effective_chat_enabled
    result = compute_effective_chat_enabled(
        mode="simple",
        raw_chat=[True, True, True, True],
        enabled_toons=[True, True, True, True],
        assignments=[0, 0],  # only first two have assignments
    )
    assert result == [True, True, False, False]


def test_effective_chat_simple_mode_short_enabled_returns_short_list():
    """The result length follows enabled_toons length (sizing the per-toon
    decisions). raw_chat shape does not affect length in either mode."""
    from tabs.multitoon._tab import compute_effective_chat_enabled
    result = compute_effective_chat_enabled(
        mode="simple",
        raw_chat=[True, True, True, True],
        enabled_toons=[True, True],
        assignments=[0, 1],
    )
    assert result == [True, False]


# ── SettingsTab back-compat shim ─────────────────────────────────────────


def test_settings_categories_use_features_key():
    """The renamed sidebar category uses the 'features' key. Old 'keep_alive'
    persisted value should resolve to the features page via shim."""
    from tabs.settings_tab import SettingsTab
    keys = [k for k, _ in SettingsTab.CATEGORIES]
    assert "features" in keys
    assert "keep_alive" not in keys
