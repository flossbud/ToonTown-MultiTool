"""LAUNCH_QUIT_CONFIRM_DISMISSED must exist as a settings key constant."""
from utils import settings_keys


def test_quit_confirm_dismissed_key_exists():
    assert hasattr(settings_keys, "LAUNCH_QUIT_CONFIRM_DISMISSED")


def test_quit_confirm_dismissed_value_is_stable():
    # Persisted key string must not change between releases without a
    # migration; pin it.
    assert settings_keys.LAUNCH_QUIT_CONFIRM_DISMISSED == "launch_quit_confirm_dismissed"
