"""Backend-level hold-shape tests for Win32Backend.

Verifies send_keydown -> send_keyup posts two distinct messages
(WM_KEYDOWN then WM_KEYUP) with the right lparam transition bits.
Mocks win32gui/win32api/win32con following the existing
test_win32_backend_modifiers.py pattern.

See docs/superpowers/specs/2026-05-26-held-key-registry-design.md.
"""

import sys
from unittest.mock import MagicMock


def _capture_two_postmessages(keysym):
    """Call send_keydown then send_keyup with the given keysym; return
    [{'msg', 'wparam', 'lparam'}, ...] for each PostMessage call."""
    fake_win32api = MagicMock()
    fake_win32api.MapVirtualKey.return_value = 0x1F
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

    backend.send_keydown("12345", keysym)
    backend.send_keyup("12345", keysym)

    calls = fake_win32gui.PostMessage.call_args_list
    return [
        {"hwnd": c[0][0], "msg": c[0][1], "wparam": c[0][2], "lparam": c[0][3]}
        for c in calls
    ]


def test_keydown_then_keyup_post_two_distinct_messages():
    posts = _capture_two_postmessages("space")
    assert len(posts) == 2, f"expected 2 PostMessage calls, got {len(posts)}: {posts}"
    assert posts[0]["msg"] == 0x100, f"first must be WM_KEYDOWN (0x100), got {posts[0]['msg']:#x}"
    assert posts[1]["msg"] == 0x101, f"second must be WM_KEYUP (0x101), got {posts[1]['msg']:#x}"


def test_keydown_lparam_has_no_transition_bits():
    """WM_KEYDOWN must NOT set bits 30 or 31. Bit 30 = previous key state
    (would imply it was already down); bit 31 = transition state (1
    indicates release). Both should be 0 on keydown."""
    posts = _capture_two_postmessages("space")
    assert not (posts[0]["lparam"] & (1 << 30)), (
        f"WM_KEYDOWN lparam must NOT set bit 30, got {posts[0]['lparam']:#x}"
    )
    assert not (posts[0]["lparam"] & (1 << 31)), (
        f"WM_KEYDOWN lparam must NOT set bit 31, got {posts[0]['lparam']:#x}"
    )


def test_keyup_lparam_sets_transition_bits():
    """WM_KEYUP must set bits 30 AND 31 in lparam, per the Windows
    keystroke message contract."""
    posts = _capture_two_postmessages("space")
    assert posts[1]["lparam"] & (1 << 30), (
        f"WM_KEYUP lparam must set bit 30, got {posts[1]['lparam']:#x}"
    )
    assert posts[1]["lparam"] & (1 << 31), (
        f"WM_KEYUP lparam must set bit 31, got {posts[1]['lparam']:#x}"
    )
