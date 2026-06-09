"""Tests for chat handling mode feature.

Covers:
- Settings key constants and normalizer.
- Pure-function effective-chat computation (four canonical modes).
- MultitoonTab integration via get_chat_handling_mode.
- Button visibility via apply_chat_handling_mode.

See: docs/superpowers/specs/2026-06-09-chat-handling-logic-dropdown-design.md
"""

from unittest.mock import MagicMock


def test_chat_handling_mode_constant_exists_and_is_string():
    """The settings key is a public constant in utils/settings_keys.py."""
    from utils.settings_keys import CHAT_HANDLING_MODE
    assert CHAT_HANDLING_MODE == "chat_handling_mode"


# ── SettingsTab back-compat shim ─────────────────────────────────────────


def test_settings_categories_use_features_key():
    """The renamed sidebar category uses the 'features' key. Old 'keep_alive'
    persisted value should resolve to the features page via shim."""
    from tabs.settings_tab import SettingsTab
    keys = [k for k, _ in SettingsTab.CATEGORIES]
    assert "features" in keys
    assert "keep_alive" not in keys


# ── New canonical-mode constants and normalizer ──────────────────────────


def test_chat_handling_mode_default_is_focused_only():
    from utils.settings_keys import CHAT_HANDLING_MODE_DEFAULT
    assert CHAT_HANDLING_MODE_DEFAULT == "focused_only"


def test_chat_handling_mode_values_tuple():
    from utils.settings_keys import (
        CHAT_HANDLING_MODE_VALUES, CHAT_HANDLING_FOCUSED_ONLY,
        CHAT_HANDLING_ALL_TOONS, CHAT_HANDLING_KEYSET_DYNAMIC,
        CHAT_HANDLING_PER_TOON,
    )
    assert CHAT_HANDLING_MODE_VALUES == (
        CHAT_HANDLING_FOCUSED_ONLY, CHAT_HANDLING_ALL_TOONS,
        CHAT_HANDLING_KEYSET_DYNAMIC, CHAT_HANDLING_PER_TOON,
    )


def test_normalize_legacy_simple_to_keyset_dynamic():
    from utils.settings_keys import normalize_chat_handling_mode
    assert normalize_chat_handling_mode("simple") == "keyset_dynamic"


def test_normalize_legacy_advanced_to_per_toon():
    from utils.settings_keys import normalize_chat_handling_mode
    assert normalize_chat_handling_mode("advanced") == "per_toon"


def test_normalize_canonical_values_pass_through():
    from utils.settings_keys import (
        normalize_chat_handling_mode, CHAT_HANDLING_MODE_VALUES,
    )
    for v in CHAT_HANDLING_MODE_VALUES:
        assert normalize_chat_handling_mode(v) == v


def test_normalize_unknown_and_none_return_default():
    from utils.settings_keys import (
        normalize_chat_handling_mode, CHAT_HANDLING_MODE_DEFAULT,
    )
    assert normalize_chat_handling_mode(None) == CHAT_HANDLING_MODE_DEFAULT
    assert normalize_chat_handling_mode("garbage") == CHAT_HANDLING_MODE_DEFAULT
    assert normalize_chat_handling_mode("") == CHAT_HANDLING_MODE_DEFAULT


def test_effective_keyset_dynamic_all_default_keyset():
    from tabs.multitoon._tab import compute_effective_chat_enabled
    assert compute_effective_chat_enabled(
        mode="keyset_dynamic", raw_chat=[True]*4,
        enabled_toons=[True]*4, assignments=[0, 0, 0, 0],
    ) == [True, True, True, True]


def test_effective_keyset_dynamic_one_non_default_keyset():
    from tabs.multitoon._tab import compute_effective_chat_enabled
    assert compute_effective_chat_enabled(
        mode="keyset_dynamic", raw_chat=[True]*4,
        enabled_toons=[True]*4, assignments=[0, 1, 0, 0],
    ) == [True, False, True, True]


def test_effective_keyset_dynamic_disabled_toon():
    from tabs.multitoon._tab import compute_effective_chat_enabled
    assert compute_effective_chat_enabled(
        mode="keyset_dynamic", raw_chat=[True]*4,
        enabled_toons=[True, False, True, True], assignments=[0, 0, 0, 0],
    ) == [True, False, True, True]


def test_effective_keyset_dynamic_short_assignments():
    from tabs.multitoon._tab import compute_effective_chat_enabled
    assert compute_effective_chat_enabled(
        mode="keyset_dynamic", raw_chat=[True]*4,
        enabled_toons=[True]*4, assignments=[0, 0],
    ) == [True, True, False, False]


def test_effective_per_toon_returns_raw():
    from tabs.multitoon._tab import compute_effective_chat_enabled
    assert compute_effective_chat_enabled(
        mode="per_toon", raw_chat=[True, False, True, False],
        enabled_toons=[True]*4, assignments=[1, 1, 1, 1],
    ) == [True, False, True, False]


def test_effective_focused_only_is_all_false():
    from tabs.multitoon._tab import compute_effective_chat_enabled
    assert compute_effective_chat_enabled(
        mode="focused_only", raw_chat=[True]*4,
        enabled_toons=[True]*4, assignments=[0, 0, 0, 0],
    ) == [False, False, False, False]


def test_effective_all_toons_enabled_only():
    from tabs.multitoon._tab import compute_effective_chat_enabled
    assert compute_effective_chat_enabled(
        mode="all_toons", raw_chat=[False]*4,
        enabled_toons=[True, False, True, True], assignments=[1, 1, 1, 1],
    ) == [True, False, True, True]


def test_effective_length_follows_enabled_toons():
    from tabs.multitoon._tab import compute_effective_chat_enabled
    assert compute_effective_chat_enabled(
        mode="keyset_dynamic", raw_chat=[True]*4,
        enabled_toons=[True, True], assignments=[0, 1],
    ) == [True, False]


def test_get_chat_handling_mode_normalizes_legacy_advanced():
    from types import SimpleNamespace
    from tabs.multitoon._tab import MultitoonTab
    sm = SimpleNamespace(get=lambda key, default=None: "advanced")
    tab = SimpleNamespace(settings_manager=sm)
    assert MultitoonTab.get_chat_handling_mode(tab) == "per_toon"


def test_get_chat_handling_mode_defaults_focused_only_without_settings():
    from types import SimpleNamespace
    from tabs.multitoon._tab import MultitoonTab
    tab = SimpleNamespace(settings_manager=None)
    assert MultitoonTab.get_chat_handling_mode(tab) == "focused_only"


def _visibility_stub(wants):
    from types import SimpleNamespace
    buttons = [MagicMock() for _ in wants]
    return SimpleNamespace(
        chat_buttons=buttons,
        _chat_button_game_wants_visible=list(wants),
    ), buttons


def test_apply_mode_shows_buttons_for_legacy_advanced():
    from tabs.multitoon._tab import MultitoonTab
    tab, buttons = _visibility_stub([True, True, False, True])
    MultitoonTab.apply_chat_handling_mode(tab, "advanced")
    buttons[0].setVisible.assert_called_with(True)
    buttons[1].setVisible.assert_called_with(True)
    buttons[2].setVisible.assert_called_with(False)
    buttons[3].setVisible.assert_called_with(True)


def test_apply_mode_hides_all_buttons_for_focused_only():
    from tabs.multitoon._tab import MultitoonTab
    tab, buttons = _visibility_stub([True, True, True, True])
    MultitoonTab.apply_chat_handling_mode(tab, "focused_only")
    for b in buttons:
        b.setVisible.assert_called_with(False)


def test_effective_per_toon_short_raw_chat_pads_false():
    """per_toon length-normalizes: missing raw_chat indices -> False, never
    an IndexError."""
    from tabs.multitoon._tab import compute_effective_chat_enabled
    assert compute_effective_chat_enabled(
        mode="per_toon", raw_chat=[True], enabled_toons=[True, True, True],
        assignments=[0, 0, 0],
    ) == [True, False, False]


def test_normalize_non_hashable_returns_default():
    """A corrupt non-string persisted value must not raise; it returns the
    default."""
    from utils.settings_keys import (
        normalize_chat_handling_mode, CHAT_HANDLING_MODE_DEFAULT,
    )
    assert normalize_chat_handling_mode([]) == CHAT_HANDLING_MODE_DEFAULT
    assert normalize_chat_handling_mode({}) == CHAT_HANDLING_MODE_DEFAULT
    assert normalize_chat_handling_mode(0) == CHAT_HANDLING_MODE_DEFAULT
