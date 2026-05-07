"""Asserts that Win32Backend posts modifier keystrokes with the SAME shape
the OS itself produces for a real key press: generic VK_CONTROL/VK_SHIFT/
VK_MENU as wparam, with L/R encoded in lparam (scan code + extended bit).

Confirmed via debug_probe_postmessage.py against a probe WindowProc:
    Real Left Ctrl  -> wparam=0x11 (VK_CONTROL), scan=0x1D, ext=0
    Real Right Ctrl -> wparam=0x11 (VK_CONTROL), scan=0x1D, ext=1
    Real Left Shift -> wparam=0x10 (VK_SHIFT),   scan=0x2A, ext=0
    Real Right Shift-> wparam=0x10 (VK_SHIFT),   scan=0x36, ext=0
    Real Left Alt   -> wparam=0x12 (VK_MENU),    scan=0x38, ext=0
    Real Right Alt  -> wparam=0x12 (VK_MENU),    scan=0x38, ext=1

The current Win32Backend posts VK_LCONTROL/VK_RCONTROL/VK_LSHIFT/VK_RSHIFT/
VK_LMENU/VK_RMENU instead. Panda3D's lookup_key() handles those, but only
sets the L/R-specific button — NOT the generic 'control'/'shift'/'alt'
button that TTR's jump/walk/map bindings actually poll.
"""
import sys
from unittest.mock import MagicMock

EXTENDED_BIT = 1 << 24


def _capture_postmessage(keysym, action="keydown"):
    fake_win32api = MagicMock()
    # Use a stub MapVirtualKey to make sure the production code does NOT
    # rely on it for modifier scan codes (the override table must hardcode
    # them). 0xFE is a poison value that doesn't match any real scan code.
    fake_win32api.MapVirtualKey.return_value = 0xFE
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
    if action == "keydown":
        backend.send_keydown("12345", keysym)
    else:
        backend.send_keyup("12345", keysym)
    if not fake_win32gui.PostMessage.called:
        return None
    args = fake_win32gui.PostMessage.call_args[0]
    return {"hwnd": args[0], "msg": args[1], "wparam": args[2], "lparam": args[3]}


def _scan(lparam):
    return (lparam >> 16) & 0xFF


def test_control_l_keydown_uses_vk_control_with_left_scan_no_ext():
    p = _capture_postmessage("Control_L", "keydown")
    assert p is not None, "PostMessage was never called"
    assert p["wparam"] == 0x11, (
        f"Control_L must post wparam=VK_CONTROL (0x11), got {p['wparam']:#x}. "
        f"Posting VK_LCONTROL (0xA2) only sets Panda3D's lcontrol button, "
        f"not the generic 'control' button TTR's jump binding polls."
    )
    assert _scan(p["lparam"]) == 0x1D, f"Left Ctrl scan code must be 0x1D, got {_scan(p['lparam']):#x}"
    assert not (p["lparam"] & EXTENDED_BIT), (
        f"Left Ctrl must NOT set the extended bit. lparam={p['lparam']:#x}"
    )


def test_control_r_keydown_uses_vk_control_with_ext_bit():
    p = _capture_postmessage("Control_R", "keydown")
    assert p is not None
    assert p["wparam"] == 0x11, f"Control_R wparam must be VK_CONTROL (0x11), got {p['wparam']:#x}"
    assert _scan(p["lparam"]) == 0x1D
    assert p["lparam"] & EXTENDED_BIT, f"Right Ctrl must set the extended bit. lparam={p['lparam']:#x}"


def test_shift_l_keydown_uses_vk_shift_with_left_scan_no_ext():
    p = _capture_postmessage("Shift_L", "keydown")
    assert p is not None
    assert p["wparam"] == 0x10, f"Shift_L wparam must be VK_SHIFT (0x10), got {p['wparam']:#x}"
    assert _scan(p["lparam"]) == 0x2A
    assert not (p["lparam"] & EXTENDED_BIT)


def test_shift_r_keydown_uses_vk_shift_with_right_scan_no_ext():
    """Right Shift is special: scan code is 0x36 and the extended bit is NOT set."""
    p = _capture_postmessage("Shift_R", "keydown")
    assert p is not None
    assert p["wparam"] == 0x10
    assert _scan(p["lparam"]) == 0x36
    assert not (p["lparam"] & EXTENDED_BIT)


def test_alt_l_keydown_uses_vk_menu_no_ext():
    p = _capture_postmessage("Alt_L", "keydown")
    assert p is not None
    assert p["wparam"] == 0x12, f"Alt_L wparam must be VK_MENU (0x12), got {p['wparam']:#x}"
    assert _scan(p["lparam"]) == 0x38
    assert not (p["lparam"] & EXTENDED_BIT)


def test_alt_r_keydown_uses_vk_menu_with_ext_bit():
    p = _capture_postmessage("Alt_R", "keydown")
    assert p is not None
    assert p["wparam"] == 0x12
    assert _scan(p["lparam"]) == 0x38
    assert p["lparam"] & EXTENDED_BIT


def test_control_l_keyup_preserves_wparam_and_sets_transition_bits():
    p = _capture_postmessage("Control_L", "keyup")
    assert p is not None
    assert p["wparam"] == 0x11
    assert _scan(p["lparam"]) == 0x1D
    assert not (p["lparam"] & EXTENDED_BIT)
    assert p["lparam"] & (1 << 30), "WM_KEYUP must set bit 30 (previous-key-state)"
    assert p["lparam"] & (1 << 31), "WM_KEYUP must set bit 31 (transition-state)"


def test_control_r_keyup_preserves_ext_bit():
    p = _capture_postmessage("Control_R", "keyup")
    assert p is not None
    assert p["wparam"] == 0x11
    assert p["lparam"] & EXTENDED_BIT


def test_modifier_overrides_ignore_mapvirtualkey():
    """The override table hardcodes scan codes; MapVirtualKey must NOT be
    consulted for modifier sends. Verifies the production code branches
    on the override table BEFORE calling MapVirtualKey."""
    fake_win32api = MagicMock()
    fake_win32api.MapVirtualKey.return_value = 0xFE  # poison
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
    Win32Backend().send_keydown("1", "Control_L")
    sc = (fake_win32gui.PostMessage.call_args[0][3] >> 16) & 0xFF
    assert sc == 0x1D, f"Modifier send must use the hardcoded 0x1D scan, not MapVirtualKey's 0xFE; got {sc:#x}"
