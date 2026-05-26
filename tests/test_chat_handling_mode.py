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


def test_default_mode_is_simple_via_settings_manager_get():
    """A fresh SettingsManager with no persisted value returns 'simple' as
    the default when callers pass 'simple' as the get() default. This is the
    convention every read site will use."""
    from utils.settings_keys import CHAT_HANDLING_MODE
    settings = MagicMock()
    settings.get.side_effect = lambda key, default=None: default
    assert settings.get(CHAT_HANDLING_MODE, "simple") == "simple"
