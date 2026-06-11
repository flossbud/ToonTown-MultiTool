"""Win32Backend mouse-injection unit tests (cross-platform). The module
already imports on Linux (its win32 imports sit in try/except); the
PostMessage path is tested by setting a fake win32gui module attribute."""
import types

import pytest

from utils import win32_backend
from utils.win32_backend import (
    MK_LBUTTON, WM_LBUTTONDOWN, WM_LBUTTONUP, WM_MOUSEMOVE,
    Win32Backend, mouse_wparam_from_state, pack_mouse_lparam,
)


def test_pack_mouse_lparam_positive():
    assert pack_mouse_lparam(500, 250) == (250 << 16) | 500


def test_pack_mouse_lparam_negative_wraps_signed_words():
    # map_point never clamps: out-of-bounds release coords can be negative
    # and must wrap as signed 16-bit words (e.g. -50 -> 0xFFCE).
    lp = pack_mouse_lparam(-50, -1)
    assert lp & 0xFFFF == 0xFFCE
    assert (lp >> 16) & 0xFFFF == 0xFFFF


def test_mouse_wparam_from_state():
    assert mouse_wparam_from_state(0) == 0
    assert mouse_wparam_from_state(0x100) == MK_LBUTTON
    assert mouse_wparam_from_state(0x400) == 0  # other buttons: not mapped


@pytest.fixture
def backend(monkeypatch):
    posted = []
    fake = types.SimpleNamespace(
        IsWindow=lambda h: h != 666,
        PostMessage=lambda h, m, w, l: posted.append((h, m, w, l)),
    )
    monkeypatch.setattr(win32_backend, "win32gui", fake, raising=False)
    return Win32Backend(), posted


def test_send_button_press_posts_lbuttondown(backend):
    b, posted = backend
    assert b.send_button_press("777", 500, 250, 1461, 281, state=0, time=5) is True
    assert posted == [(777, WM_LBUTTONDOWN, MK_LBUTTON, (250 << 16) | 500)]


def test_send_button_release_posts_lbuttonup_wparam_zero(backend):
    b, posted = backend
    # Drains pass state with Button1Mask set; WM_LBUTTONUP wParam excludes
    # the button being released, so it is 0 regardless.
    assert b.send_button_release("777", 500, 250, 0, 0, state=0x100) is True
    assert posted == [(777, WM_LBUTTONUP, 0, (250 << 16) | 500)]


def test_send_motion_carries_drag_flag_from_state(backend):
    b, posted = backend
    b.send_motion("777", 10, 20, 0, 0, state=0x100)
    b.send_motion("777", 11, 20, 0, 0, state=0)
    assert posted[0][1:3] == (WM_MOUSEMOVE, MK_LBUTTON)
    assert posted[1][1:3] == (WM_MOUSEMOVE, 0)


def test_dead_hwnd_returns_false_without_posting(backend):
    b, posted = backend
    assert b.send_button_press("666", 1, 1, 0, 0) is False
    assert posted == []


def test_malformed_wid_returns_false(backend):
    b, posted = backend
    assert b.send_motion("0xNOPE", 1, 1, 0, 0) is False
    assert posted == []
