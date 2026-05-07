"""Repro for v2.1.3 issue 7: keep-alive jump on Left Ctrl doesn't fire on Windows.

Hardened in 2.2.x: previously this only checked the extended-key bit and
missed the actual root cause — Win32Backend was posting VK_LCONTROL/
VK_RCONTROL as wparam, but real Windows keystrokes deliver the generic
VK_CONTROL (0x11) regardless of side, with L/R encoded in lparam. Panda3D's
generic 'control' button — which TTR's jump binding polls — is only set
when wparam == VK_CONTROL.

We test the full PostMessage payload directly so the test runs on any
platform.
"""
import sys
from unittest.mock import MagicMock

EXTENDED_BIT = 1 << 24


def _captured_postmessage_for_ctrl(side):
    fake_win32api = MagicMock()
    fake_win32api.MapVirtualKey.return_value = 0x1D
    fake_win32gui = MagicMock()
    fake_win32con = MagicMock()
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
    keysym = "Control_L" if side == "left" else "Control_R"
    backend.send_keydown("12345", keysym)
    if not fake_win32gui.PostMessage.called:
        return None
    args = fake_win32gui.PostMessage.call_args[0]
    return {"wparam": args[2], "lparam": args[3]}


def test_right_ctrl_keydown_uses_vk_control_with_extended_bit():
    """Right Ctrl: real OS keystroke is wparam=VK_CONTROL (0x11) with the
    extended-key bit set in lparam. Posting VK_RCONTROL (0xA3) bypasses the
    generic-control button TTR's jump binding polls."""
    p = _captured_postmessage_for_ctrl("right")
    assert p is not None
    assert p["wparam"] == 0x11, (
        f"Control_R wparam must be VK_CONTROL (0x11), got {p['wparam']:#x}"
    )
    assert p["lparam"] & EXTENDED_BIT, (
        f"WM_KEYDOWN lparam for Control_R missing extended bit. lparam={p['lparam']:#08x}"
    )


def test_left_ctrl_keydown_uses_vk_control_without_extended_bit():
    """Left Ctrl: real OS keystroke is wparam=VK_CONTROL (0x11), ext=0.
    Posting VK_LCONTROL (0xA2) was the v2.1.3 keep-alive jump regression."""
    p = _captured_postmessage_for_ctrl("left")
    assert p is not None
    assert p["wparam"] == 0x11, (
        f"Control_L wparam must be VK_CONTROL (0x11), got {p['wparam']:#x}"
    )
    assert not (p["lparam"] & EXTENDED_BIT), (
        f"Left Ctrl must NOT set the extended bit. lparam={p['lparam']:#08x}"
    )
