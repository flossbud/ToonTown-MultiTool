"""Win32Backend mouse-injection unit tests (cross-platform). The module
already imports on Linux (its win32 imports sit in try/except); the
PostMessage path is tested by setting a fake win32gui module attribute."""
import types

import pytest

from utils import win32_backend
from utils.win32_backend import (
    MK_LBUTTON, WM_LBUTTONDOWN, WM_LBUTTONUP, WM_MOUSEMOVE,
    Win32Backend, pack_mouse_lparam,
)


def test_pack_mouse_lparam_positive():
    assert pack_mouse_lparam(500, 250) == (250 << 16) | 500


def test_pack_mouse_lparam_negative_wraps_signed_words():
    # map_point never clamps: out-of-bounds release coords can be negative
    # and must wrap as signed 16-bit words (e.g. -50 -> 0xFFCE).
    lp = pack_mouse_lparam(-50, -1)
    assert lp & 0xFFFF == 0xFFCE
    assert (lp >> 16) & 0xFFFF == 0xFFFF


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


def test_dead_hwnd_returns_false_without_posting(backend):
    b, posted = backend
    assert b.send_button_press("666", 1, 1, 0, 0) is False
    assert posted == []


def test_malformed_wid_returns_false(backend):
    b, posted = backend
    assert b.send_motion("0xNOPE", 1, 1, 0, 0) is False
    assert posted == []


def test_non_left_button_refused(backend):
    b, posted = backend
    assert b.send_button_press("777", 1, 1, 0, 0, button=3) is False
    assert b.send_button_release("777", 1, 1, 0, 0, button=2) is False
    assert posted == []


# ── X-button position carrier (hover + drag motion) ────────────────────

from utils.win32_backend import WM_XBUTTONDOWN, WM_XBUTTONUP, CARRY_IDLE_S


@pytest.fixture
def clock(monkeypatch):
    t = {"now": 1000.0}
    monkeypatch.setattr(win32_backend, "monotonic", lambda: t["now"])
    return t


def test_send_motion_posts_invalid_selector_xbutton_pair(backend, clock):
    b, posted = backend
    assert b.send_motion("777", 500, 250, 0, 0, state=0) is True
    assert posted == [
        (777, WM_XBUTTONDOWN, 0, (250 << 16) | 500),
        (777, WM_XBUTTONUP, 0, (250 << 16) | 500),
    ]


def test_send_motion_drag_carries_mk_lbutton_low_word(backend, clock):
    b, posted = backend
    b.send_motion("777", 10, 20, 0, 0, state=0x100)  # Button1Mask = drag
    assert posted[0][:3] == (777, WM_XBUTTONDOWN, 0x0001)
    assert posted[1][:3] == (777, WM_XBUTTONUP, 0x0001)


def test_send_motion_never_posts_wm_mousemove(backend, clock):
    b, posted = backend
    b.send_motion("777", 1, 2, 0, 0, state=0)
    b.send_motion("777", 3, 4, 0, 0, state=0x100)
    assert all(m != WM_MOUSEMOVE for (_h, m, _w, _l) in posted)


def test_gate_suppresses_exact_duplicate_within_idle_window(backend, clock):
    b, posted = backend
    b.send_motion("777", 100, 100, 0, 0, state=0)   # carries
    posted.clear()
    clock["now"] += CARRY_IDLE_S / 2                 # still "active"
    b.send_motion("777", 100, 100, 0, 0, state=0)   # exact dup -> suppressed
    assert posted == []


def test_gate_carries_changed_point_within_idle_window(backend, clock):
    b, posted = backend
    b.send_motion("777", 100, 100, 0, 0, state=0)
    posted.clear()
    clock["now"] += CARRY_IDLE_S / 2
    b.send_motion("777", 101, 100, 0, 0, state=0)   # moved -> carries
    assert len(posted) == 2


def test_gate_carries_first_motion_after_idle_even_if_same_point(backend, clock):
    b, posted = backend
    b.send_motion("777", 100, 100, 0, 0, state=0)
    posted.clear()
    clock["now"] += CARRY_IDLE_S * 2                 # idle elapsed
    b.send_motion("777", 100, 100, 0, 0, state=0)   # same point but re-armed
    assert len(posted) == 2


def test_idle_timer_uses_request_time_not_carry_time(backend, clock):
    b, posted = backend
    b.send_motion("777", 100, 100, 0, 0, state=0)   # carries
    for _ in range(5):
        clock["now"] += CARRY_IDLE_S * 0.9           # each < idle, cumulative > idle
        b.send_motion("777", 100, 100, 0, 0, state=0)  # dup
    posted.clear()
    clock["now"] += CARRY_IDLE_S * 0.9
    b.send_motion("777", 100, 100, 0, 0, state=0)
    assert posted == []  # still suppressed: requests kept it "active"


def test_partial_pair_invalidates_cache(backend, clock, monkeypatch):
    b, posted = backend
    calls = {"n": 0}
    real_post = b._post_mouse

    def flaky(win, msg, wp, x, y):
        calls["n"] += 1
        if calls["n"] == 2:   # the UP
            return False
        return real_post(win, msg, wp, x, y)

    monkeypatch.setattr(b, "_post_mouse", flaky)
    b.send_motion("777", 100, 100, 0, 0, state=0)   # DOWN ok, UP fails
    posted.clear()
    monkeypatch.setattr(b, "_post_mouse", real_post)
    clock["now"] += CARRY_IDLE_S / 2                 # within idle window
    b.send_motion("777", 100, 100, 0, 0, state=0)   # cache invalidated -> carries
    assert len(posted) == 2


def test_send_button_press_updates_carried_point(backend, clock):
    b, posted = backend
    b.send_button_press("777", 100, 100, 0, 0, state=0)  # click moves sticky pointer
    posted.clear()
    clock["now"] += CARRY_IDLE_S / 2                      # within idle window
    b.send_motion("777", 100, 100, 0, 0, state=0)        # same point -> suppressed
    assert posted == []


def test_carrier_dead_hwnd_returns_false(backend, clock):
    b, posted = backend
    assert b.send_motion("666", 1, 1, 0, 0, state=0) is False  # IsWindow false
    assert posted == []
