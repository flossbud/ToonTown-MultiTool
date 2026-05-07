"""Repro for v2.1.3 issue 7: keep-alive jump on Left Ctrl doesn't fire on Windows.

Hypothesis: Right Ctrl is a Win32 extended key and needs bit 24 of lparam set.
Left Ctrl is NOT extended. The fix targets the documented extended-key set
(arrows, right-side modifiers, nav keys); if A.4 manual verification shows
Left-Ctrl behavior is still broken, that's a separate follow-up.

We test the lparam construction directly so the test runs on any platform.
"""
import sys
from unittest.mock import MagicMock

EXTENDED_BIT = 1 << 24


def _captured_lparam_for_ctrl(side):
    fake_win32api = MagicMock()
    fake_win32api.MapVirtualKey.return_value = 0x1D
    fake_win32gui = MagicMock()
    fake_win32con = MagicMock()
    fake_win32con.VK_LCONTROL = 0xA2
    fake_win32con.VK_RCONTROL = 0xA3
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
    return fake_win32gui.PostMessage.call_args[0][3]


def test_right_ctrl_keydown_sets_extended_bit():
    """Right Ctrl is always an extended key per Win32 spec."""
    lparam = _captured_lparam_for_ctrl("right")
    assert lparam is not None
    assert lparam & EXTENDED_BIT, (
        f"WM_KEYDOWN lparam for Control_R missing extended bit. Got 0x{lparam:08X}."
    )


def test_left_ctrl_keydown_does_not_set_extended_bit():
    """Left Ctrl is NOT extended; only Right Ctrl is. Sanity check the rule isn't applied universally."""
    lparam = _captured_lparam_for_ctrl("left")
    assert lparam is not None
    assert not (lparam & EXTENDED_BIT)
