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
