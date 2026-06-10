"""Settings key + default for click sync."""
from utils.settings_keys import CLICK_SYNC_ENABLED


def test_key_value():
    assert CLICK_SYNC_ENABLED == "click_sync_enabled"
