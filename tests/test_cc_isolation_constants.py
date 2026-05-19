"""Constants tests for utils/cc_isolation.py."""

from utils import cc_isolation


def test_wasd_canonical_keymap_is_movement_only():
    assert cc_isolation.CANONICAL_KEYMAP["wasd"] == {
        "forward": "w",
        "reverse": "s",
        "left": "a",
        "right": "d",
    }


def test_arrows_canonical_keymap_is_movement_only():
    assert cc_isolation.CANONICAL_KEYMAP["arrows"] == {
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
    assert cc_isolation.canonical_to_ttmt_keysyms("wasd") == {
        "forward": "w",
        "reverse": "s",
        "left": "a",
        "right": "d",
    }


def test_canonical_to_ttmt_keysym_arrows():
    assert cc_isolation.canonical_to_ttmt_keysyms("arrows") == {
        "forward": "Up",
        "reverse": "Down",
        "left": "Left",
        "right": "Right",
    }
