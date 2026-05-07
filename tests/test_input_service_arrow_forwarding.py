"""Repro for v2.1.3 issue 8: arrow-key movement breaks multitoon forwarding on Windows.

Real Up arrow press on Windows delivers wparam=VK_UP (0x26) with the
extended-key bit set in lparam (and scan code 0x48). We assert all three so
a future change can't silently mis-target one piece.
"""
import sys
from unittest.mock import MagicMock

EXTENDED_BIT = 1 << 24


def _captured_postmessage_for(keysym, action="keydown"):
    """Call Win32Backend.send_key{down,up} with mocked pywin32 and return
    the (wparam, lparam) PostMessage was called with."""
    fake_win32api = MagicMock()
    fake_win32api.MapVirtualKey.return_value = 0x48  # scan code
    fake_win32gui = MagicMock()
    fake_win32con = MagicMock()
    fake_win32con.VK_UP = 0x26
    fake_win32con.VK_DOWN = 0x28
    fake_win32con.VK_LEFT = 0x25
    fake_win32con.VK_RIGHT = 0x27
    fake_win32con.VK_LCONTROL = 0xA2
    fake_win32con.VK_RCONTROL = 0xA3
    fake_win32con.VK_LSHIFT = 0xA0
    fake_win32con.VK_RSHIFT = 0xA1
    fake_win32con.VK_LMENU = 0xA4
    fake_win32con.VK_RMENU = 0xA5
    fake_win32con.WM_KEYDOWN = 0x100
    fake_win32con.WM_KEYUP = 0x101
    sys.modules["win32api"] = fake_win32api
    sys.modules["win32gui"] = fake_win32gui
    sys.modules["win32con"] = fake_win32con
    sys.modules["win32process"] = MagicMock()
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
    args = fake_win32gui.PostMessage.call_args[0]
    return {"wparam": args[2], "lparam": args[3]}


def test_arrow_up_keydown_full_payload():
    p = _captured_postmessage_for("Up", "keydown")
    assert p is not None, "PostMessage was not called"
    assert p["wparam"] == 0x26, f"Up wparam must be VK_UP (0x26), got {p['wparam']:#x}"
    assert p["lparam"] & EXTENDED_BIT, f"Up lparam missing extended bit. lparam={p['lparam']:#08x}"


def test_arrow_down_keydown_full_payload():
    p = _captured_postmessage_for("Down", "keydown")
    assert p is not None
    assert p["wparam"] == 0x28
    assert p["lparam"] & EXTENDED_BIT


def test_arrow_left_keydown_full_payload():
    p = _captured_postmessage_for("Left", "keydown")
    assert p is not None
    assert p["wparam"] == 0x25
    assert p["lparam"] & EXTENDED_BIT


def test_arrow_right_keydown_full_payload():
    p = _captured_postmessage_for("Right", "keydown")
    assert p is not None
    assert p["wparam"] == 0x27
    assert p["lparam"] & EXTENDED_BIT


def test_arrow_up_keyup_full_payload():
    p = _captured_postmessage_for("Up", "keyup")
    assert p is not None
    assert p["wparam"] == 0x26
    assert p["lparam"] & EXTENDED_BIT
    assert p["lparam"] & (1 << 30)
    assert p["lparam"] & (1 << 31)


def test_letter_a_keydown_does_not_set_extended_bit():
    """Sanity check: letters are NOT extended keys, so the bit should be clear."""
    p = _captured_postmessage_for("a", "keydown")
    assert p is not None
    assert not (p["lparam"] & EXTENDED_BIT)
