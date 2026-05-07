"""Win32Backend must be able to send the navigation cluster (Home, End,
Page Up/Down, Insert) and function keys F1-F12. TTR's default control
bindings use these for stickerBook (f8), showGags (home), showTasks (end),
lookUp/lookDown (page_up/page_down).

Real OS keystrokes for the dedicated nav cluster set the extended-key bit;
F-keys do not. Verified via win32api.MapVirtualKey on Windows 11."""
import sys
from unittest.mock import MagicMock

EXTENDED_BIT = 1 << 24


def _captured_postmessage_for(keysym):
    fake_win32api = MagicMock()
    # Map each VK code to its expected scan code so we can assert on it.
    def map_vk(vk, mapType):
        return {
            0x24: 0x47,  # VK_HOME
            0x23: 0x4F,  # VK_END
            0x21: 0x49,  # VK_PRIOR (PgUp)
            0x22: 0x51,  # VK_NEXT (PgDn)
            0x2D: 0x52,  # VK_INSERT
            0x70: 0x3B,  # VK_F1
            0x77: 0x42,  # VK_F8
            0x7B: 0x58,  # VK_F12
        }.get(vk, 0xFE)
    fake_win32api.MapVirtualKey.side_effect = map_vk
    fake_win32gui = MagicMock()
    fake_win32con = MagicMock()
    fake_win32con.VK_HOME = 0x24
    fake_win32con.VK_END = 0x23
    fake_win32con.VK_PRIOR = 0x21
    fake_win32con.VK_NEXT = 0x22
    fake_win32con.VK_INSERT = 0x2D
    fake_win32con.VK_F1 = 0x70
    fake_win32con.VK_F2 = 0x71
    fake_win32con.VK_F3 = 0x72
    fake_win32con.VK_F4 = 0x73
    fake_win32con.VK_F5 = 0x74
    fake_win32con.VK_F6 = 0x75
    fake_win32con.VK_F7 = 0x76
    fake_win32con.VK_F8 = 0x77
    fake_win32con.VK_F9 = 0x78
    fake_win32con.VK_F10 = 0x79
    fake_win32con.VK_F11 = 0x7A
    fake_win32con.VK_F12 = 0x7B
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
    Win32Backend().send_keydown("12345", keysym)
    if not fake_win32gui.PostMessage.called:
        return None
    args = fake_win32gui.PostMessage.call_args[0]
    return {"wparam": args[2], "lparam": args[3]}


def test_home_uses_vk_home_with_ext_bit():
    p = _captured_postmessage_for("Home")
    assert p is not None, "Win32Backend dropped 'Home' silently"
    assert p["wparam"] == 0x24
    assert p["lparam"] & EXTENDED_BIT


def test_end_uses_vk_end_with_ext_bit():
    p = _captured_postmessage_for("End")
    assert p is not None
    assert p["wparam"] == 0x23
    assert p["lparam"] & EXTENDED_BIT


def test_page_up_uses_vk_prior_with_ext_bit():
    p = _captured_postmessage_for("Prior")
    assert p is not None
    assert p["wparam"] == 0x21
    assert p["lparam"] & EXTENDED_BIT


def test_page_down_uses_vk_next_with_ext_bit():
    p = _captured_postmessage_for("Next")
    assert p is not None
    assert p["wparam"] == 0x22
    assert p["lparam"] & EXTENDED_BIT


def test_insert_uses_vk_insert_with_ext_bit():
    p = _captured_postmessage_for("Insert")
    assert p is not None
    assert p["wparam"] == 0x2D
    assert p["lparam"] & EXTENDED_BIT


def test_f1_uses_vk_f1_no_ext():
    p = _captured_postmessage_for("F1")
    assert p is not None
    assert p["wparam"] == 0x70
    assert not (p["lparam"] & EXTENDED_BIT)


def test_f8_uses_vk_f8_no_ext():
    """TTR's default stickerBook binding is F8."""
    p = _captured_postmessage_for("F8")
    assert p is not None
    assert p["wparam"] == 0x77
    assert not (p["lparam"] & EXTENDED_BIT)


def test_f12_uses_vk_f12_no_ext():
    p = _captured_postmessage_for("F12")
    assert p is not None
    assert p["wparam"] == 0x7B
    assert not (p["lparam"] & EXTENDED_BIT)
