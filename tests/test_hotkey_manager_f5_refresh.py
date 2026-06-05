"""F5 must fire HotkeyManager.refresh_requested exactly once per physical press
(not on auto-repeat), re-fire after release, never enter the InputService key
queue, only fire while input capture is allowed, and not stay wedged when the
listener stops mid-hold."""
from __future__ import annotations

import queue
from unittest.mock import MagicMock

from services.hotkey_manager import HotkeyManager


def _make_hotkey_manager(capture: bool = True):
    wm = MagicMock()
    wm.should_capture_input.return_value = capture
    q = queue.Queue(maxsize=10)
    hm = HotkeyManager(wm, q)
    return hm, q


def _fake_key(char: str = None, name: str = None, vk: int = None):
    k = MagicMock()
    k.char = char
    k.name = name
    k.vk = vk
    return k


def _f5():
    # pynput exposes F5 as a named key 'f5'; normalize_key -> 'F5'.
    return _fake_key(name="f5")


def _spy(hm):
    fired = []
    hm.refresh_requested.connect(lambda: fired.append(1))
    return fired


def test_f5_press_emits_once_and_is_not_enqueued():
    hm, q = _make_hotkey_manager()
    fired = _spy(hm)
    assert hm.on_global_key_press(_f5()) is None
    assert fired == [1]
    assert q.qsize() == 0  # F5 is a tool hotkey, never routed to the input queue


def test_f5_autorepeat_does_not_re_emit():
    hm, q = _make_hotkey_manager()
    fired = _spy(hm)
    hm.on_global_key_press(_f5())   # initial press
    hm.on_global_key_press(_f5())   # OS auto-repeat while still held
    hm.on_global_key_press(_f5())
    assert fired == [1]
    assert q.qsize() == 0


def test_f5_re_emits_after_release():
    hm, q = _make_hotkey_manager()
    fired = _spy(hm)
    hm.on_global_key_press(_f5())
    assert hm.on_global_key_release(_f5()) is None
    assert q.qsize() == 0           # release is not enqueued either
    hm.on_global_key_press(_f5())   # fresh press
    assert fired == [1, 1]


def test_f5_does_not_emit_when_capture_disabled():
    hm, q = _make_hotkey_manager(capture=False)
    fired = _spy(hm)
    assert hm.on_global_key_press(_f5()) is None
    assert fired == []
    assert q.qsize() == 0


def test_stop_listener_resets_f5_down():
    hm, _ = _make_hotkey_manager()
    fired = _spy(hm)
    hm.on_global_key_press(_f5())
    hm.is_listening = True
    hm.listener = MagicMock()
    hm._stop_listener()
    hm.on_global_key_press(_f5())
    assert fired == [1, 1]


def test_f5_held_across_stop_emits_at_most_one_extra():
    # Codifies the accepted, bounded tradeoff of resetting _f5_down in
    # _stop_listener: F5 physically held across a listener stop+restart (a focus
    # excursion) emits exactly ONE extra refresh on the restarted listener's
    # auto-repeat, then stays bounded for the rest of that hold (not unbounded
    # spam). The single extra is coalesced downstream by manual_refresh's cooldown.
    hm, _ = _make_hotkey_manager()
    fired = _spy(hm)
    hm.on_global_key_press(_f5())   # initial press -> 1 emit
    hm.is_listening = True
    hm.listener = MagicMock()
    hm._stop_listener()             # focus-out: _f5_down reset
    hm.on_global_key_press(_f5())   # restart + auto-repeat (still held) -> 1 extra
    hm.on_global_key_press(_f5())   # further auto-repeat, same session -> no emit
    assert fired == [1, 1]          # exactly one extra, then bounded
