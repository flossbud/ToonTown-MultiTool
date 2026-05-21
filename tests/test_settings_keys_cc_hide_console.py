"""Tests for the new CC_HIDE_LAUNCH_CONSOLE settings key."""

from utils import settings_keys


def test_cc_hide_launch_console_key_defined():
    assert hasattr(settings_keys, "CC_HIDE_LAUNCH_CONSOLE")
    assert settings_keys.CC_HIDE_LAUNCH_CONSOLE == "cc_hide_launch_console"
