"""Pure-constants tests for the CC isolation feature."""

from utils import cc_isolation
from utils import settings_keys


def test_settings_keys_present():
    assert settings_keys.ISOLATION_ENABLED == "isolation_enabled"
    assert settings_keys.ISOLATION_CANONICAL == "isolation_canonical"
    assert settings_keys.ISOLATION_USE_INPUT_GRAB == "isolation_use_input_grab"


def test_wasd_canonical_keymap_is_movement_only():
    km = cc_isolation.CANONICAL_KEYMAP["wasd"]
    assert km == {
        "forward": "w",
        "reverse": "s",
        "left": "a",
        "right": "d",
    }


def test_arrows_canonical_keymap_is_movement_only():
    km = cc_isolation.CANONICAL_KEYMAP["arrows"]
    assert km == {
        "forward": "arrow_up",
        "reverse": "arrow_down",
        "left": "arrow_left",
        "right": "arrow_right",
    }


def test_movement_actions_constant():
    assert cc_isolation.MOVEMENT_ACTIONS == ("forward", "reverse", "left", "right")


def test_default_canonical_is_wasd():
    assert cc_isolation.DEFAULT_CANONICAL == "wasd"


def test_canonical_to_ttmt_keysym_wasd():
    """The TTMT-internal keysym that maps to each canonical action,
    used by _send_logical_action_km to find the right outbound key."""
    m = cc_isolation.canonical_to_ttmt_keysyms("wasd")
    assert m == {
        "forward": "w",
        "reverse": "s",
        "left": "a",
        "right": "d",
    }


def test_canonical_to_ttmt_keysym_arrows():
    m = cc_isolation.canonical_to_ttmt_keysyms("arrows")
    assert m == {
        "forward": "Up",
        "reverse": "Down",
        "left": "Left",
        "right": "Right",
    }
