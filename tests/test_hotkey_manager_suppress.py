"""Tests for HotkeyManager.suppress_predicate gating."""

from __future__ import annotations

import queue
from unittest.mock import MagicMock

from services.hotkey_manager import HotkeyManager


def _make_hotkey_manager(predicate=None):
    wm = MagicMock()
    wm.should_capture_input.return_value = True
    q = queue.Queue(maxsize=10)
    hm = HotkeyManager(wm, q, suppress_predicate=predicate)
    return hm, q


def _fake_pynput_key(char: str = None, name: str = None, vk: int = None):
    """Build a minimal duck-typed pynput key object."""
    k = MagicMock()
    k.char = char
    k.name = name
    k.vk = vk
    return k


class TestSuppressPredicate:
    def test_no_predicate_returns_none(self):
        hm, q = _make_hotkey_manager(predicate=None)
        result = hm.on_global_key_press(_fake_pynput_key(name="up"))
        assert result is None
        assert q.qsize() == 1

    def test_predicate_true_does_not_stop_listener(self):
        # Returning False from a pynput callback raises StopException and KILLS
        # the listener. on_press must therefore ALWAYS return None; suppression
        # is the platform layer's job (win32 event filter / X11 grab), not here.
        hm, q = _make_hotkey_manager(predicate=lambda key: True)
        result = hm.on_global_key_press(_fake_pynput_key(name="up"))
        assert result is None
        assert q.qsize() == 1  # event still enqueued

    def test_predicate_returning_false_returns_none(self):
        hm, q = _make_hotkey_manager(predicate=lambda key: False)
        result = hm.on_global_key_press(_fake_pynput_key(name="up"))
        assert result is None
        assert q.qsize() == 1

    def test_predicate_raising_returns_none(self):
        def boom(_k):
            raise RuntimeError("oops")
        hm, q = _make_hotkey_manager(predicate=boom)
        result = hm.on_global_key_press(_fake_pynput_key(name="up"))
        assert result is None
        assert q.qsize() == 1

    def test_keyup_does_not_stop_listener(self):
        hm, q = _make_hotkey_manager(predicate=lambda key: True)
        result = hm.on_global_key_release(_fake_pynput_key(name="up"))
        assert result is None
        assert q.qsize() == 1

    def test_on_press_no_longer_calls_suppress_predicate(self):
        # Suppression moved OFF the on_press path (returning False there raised
        # StopException and killed the listener on Windows). The predicate is now
        # consulted only by the win32 event filter — see
        # test_hotkey_manager_win32_suppress.py — never by on_press/on_release.
        seen: list[str] = []
        def capture(key: str) -> bool:
            seen.append(key)
            return False
        hm, _ = _make_hotkey_manager(predicate=capture)
        hm.on_global_key_press(_fake_pynput_key(name="up"))
        hm.on_global_key_press(_fake_pynput_key(char="w"))
        assert seen == []  # on_press does not call the predicate anymore
