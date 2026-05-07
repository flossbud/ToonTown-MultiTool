"""Repro for v2.1.3 issue 8: arrow-key movement breaks multitoon forwarding on Windows.

The bug lives in win32_backend._send: the WM_KEYDOWN lparam doesn't set the
extended-key bit (bit 24, 0x01000000), which Panda3D relies on to distinguish
real arrow-key presses from numpad arrows. We test the lparam construction
directly so the test runs on any platform.
"""
import sys
from unittest.mock import MagicMock

EXTENDED_BIT = 1 << 24


def _captured_lparam_for(keysym, action="keydown"):
    """Call Win32Backend.send_key{down,up} with mocked pywin32 and return the lparam
    PostMessage was called with. Returns None if PostMessage wasn't called."""
    fake_win32api = MagicMock()
    fake_win32api.MapVirtualKey.return_value = 0x48  # any non-zero scan code
    fake_win32gui = MagicMock()
    fake_win32con = MagicMock()
    fake_win32con.VK_UP = 0x26
    fake_win32con.VK_DOWN = 0x28
    fake_win32con.VK_LEFT = 0x25
    fake_win32con.VK_RIGHT = 0x27
    fake_win32con.VK_LCONTROL = 0xA2
    fake_win32con.VK_RCONTROL = 0xA3
    fake_win32con.WM_KEYDOWN = 0x100
    fake_win32con.WM_KEYUP = 0x101
    sys.modules["win32api"] = fake_win32api
    sys.modules["win32gui"] = fake_win32gui
    sys.modules["win32con"] = fake_win32con
    sys.modules["win32process"] = MagicMock()

    # Force a fresh import of the backend with our mocked deps.
    if "utils.win32_backend" in sys.modules:
        del sys.modules["utils.win32_backend"]
    from utils.win32_backend import Win32Backend

    backend = Win32Backend()
    if action == "keydown":
        backend.send_keydown("12345", keysym)
    else:
        backend.send_keyup("12345", keysym)

    if not fake_win32gui.PostMessage.called:
        return None
    return fake_win32gui.PostMessage.call_args[0][3]  # lparam


def test_arrow_up_keydown_sets_extended_bit():
    lparam = _captured_lparam_for("Up", "keydown")
    assert lparam is not None, "PostMessage was not called"
    assert lparam & EXTENDED_BIT, (
        f"WM_KEYDOWN lparam for 'Up' is missing extended-key bit "
        f"(bit 24). Got 0x{lparam:08X}."
    )


def test_arrow_down_keydown_sets_extended_bit():
    lparam = _captured_lparam_for("Down", "keydown")
    assert lparam is not None
    assert lparam & EXTENDED_BIT


def test_arrow_left_keydown_sets_extended_bit():
    lparam = _captured_lparam_for("Left", "keydown")
    assert lparam is not None
    assert lparam & EXTENDED_BIT


def test_arrow_right_keydown_sets_extended_bit():
    lparam = _captured_lparam_for("Right", "keydown")
    assert lparam is not None
    assert lparam & EXTENDED_BIT


def test_arrow_up_keyup_sets_extended_bit():
    lparam = _captured_lparam_for("Up", "keyup")
    assert lparam is not None
    assert lparam & EXTENDED_BIT


def test_letter_a_keydown_does_not_set_extended_bit():
    """Sanity check: letters are NOT extended keys, so the bit should be clear."""
    lparam = _captured_lparam_for("a", "keydown")
    assert lparam is not None
    assert not (lparam & EXTENDED_BIT)
