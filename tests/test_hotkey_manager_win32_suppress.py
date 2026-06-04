"""Tests for the Windows win32_event_filter suppression path in HotkeyManager.

Regression guard for the bug where returning False from a pynput callback to
"suppress" actually raised StopException and STOPPED the listener on Windows
(symptom: the first grabbed key stuck on a background toon, then no input
worked at all). Suppression now goes through the pynput win32 event filter,
which calls suppress_event() and never stops the listener.

Run: TTMT_NO_VENV_REEXEC=1 QT_QPA_PLATFORM=offscreen pytest tests/test_hotkey_manager_win32_suppress.py -v
"""
from __future__ import annotations

import queue
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

from services.hotkey_manager import HotkeyManager, _WM_KEYDOWN, _WM_KEYUP


VK_A = 0x41   # -> "a" (a grabbed movement key)
VK_H = 0x48   # 'h' — not a movement key the grabber ever suppresses


def _make_hk(suppress=None, should_capture=True):
    wm = MagicMock()
    wm.should_capture_input.return_value = should_capture
    q: queue.Queue = queue.Queue()
    hk = HotkeyManager(wm, q, suppress_predicate=suppress)
    return hk, q, wm


def _data(vk):
    return SimpleNamespace(vkCode=vk)


class _FakeListener:
    def __init__(self):
        self.suppressed = 0

    def suppress_event(self):
        self.suppressed += 1


class _FakeKey:
    def __init__(self, char):
        self.char = char


class _FakeKbd:
    class Key:
        ctrl_l = object()
        ctrl_r = object()


# ── The win32 event filter ──────────────────────────────────────────────────

class TestWin32EventFilter:
    def test_non_movement_key_passes_through(self):
        hk, q, _ = _make_hk(suppress=lambda k: True)
        hk.listener = _FakeListener()
        assert hk._win32_event_filter(_WM_KEYDOWN, _data(VK_H)) is True
        assert q.empty()
        assert hk.listener.suppressed == 0

    def test_movement_key_not_suppressed_passes_through(self):
        # on_press will enqueue it; the filter must not, and must not suppress.
        hk, q, _ = _make_hk(suppress=lambda k: False)
        hk.listener = _FakeListener()
        assert hk._win32_event_filter(_WM_KEYDOWN, _data(VK_A)) is True
        assert q.empty()
        assert hk.listener.suppressed == 0

    def test_suppressed_keydown_enqueues_and_suppresses(self):
        hk, q, _ = _make_hk(suppress=lambda k: True, should_capture=True)
        hk.listener = _FakeListener()
        hk._win32_event_filter(_WM_KEYDOWN, _data(VK_A))
        assert q.get_nowait() == ("keydown", "a")
        assert hk.listener.suppressed == 1

    def test_suppressed_keyup_enqueues_and_suppresses(self):
        hk, q, _ = _make_hk(suppress=lambda k: True)
        hk.listener = _FakeListener()
        hk._win32_event_filter(_WM_KEYUP, _data(VK_A))
        assert q.get_nowait() == ("keyup", "a")
        assert hk.listener.suppressed == 1

    def test_suppressed_keydown_without_capture_neither_enqueues_nor_suppresses(self):
        # No game focused: pass the key natively, do not steal it.
        hk, q, _ = _make_hk(suppress=lambda k: True, should_capture=False)
        hk.listener = _FakeListener()
        assert hk._win32_event_filter(_WM_KEYDOWN, _data(VK_A)) is True
        assert q.empty()
        assert hk.listener.suppressed == 0

    def test_no_suppress_predicate_passes_through(self):
        hk, q, _ = _make_hk(suppress=None)
        hk.listener = _FakeListener()
        assert hk._win32_event_filter(_WM_KEYDOWN, _data(VK_A)) is True
        assert q.empty()
        assert hk.listener.suppressed == 0

    def test_filter_passes_normalized_keysym_to_predicate(self):
        seen: list[str] = []
        hk, _, _ = _make_hk(suppress=lambda k: seen.append(k) or True)
        hk.listener = _FakeListener()
        hk._win32_event_filter(_WM_KEYDOWN, _data(VK_A))     # 0x41 -> "a"
        hk._win32_event_filter(_WM_KEYDOWN, _data(0x26))     # VK_UP -> "Up"
        assert seen == ["a", "Up"]


# ── The critical regression guard: callbacks must NEVER return False ─────────

class TestCallbacksNeverStopListener:
    def test_on_press_returns_none_even_when_suppress_true(self, monkeypatch):
        import services.hotkey_manager as hm
        monkeypatch.setattr(hm, "_keyboard_module", lambda: _FakeKbd)
        hk, q, _ = _make_hk(suppress=lambda k: True, should_capture=True)
        result = hk.on_global_key_press(_FakeKey("w"))
        assert result is None  # False would raise StopException and kill the listener
        assert q.get_nowait() == ("keydown", "w")

    def test_on_release_returns_none_even_when_suppress_true(self, monkeypatch):
        import services.hotkey_manager as hm
        monkeypatch.setattr(hm, "_keyboard_module", lambda: _FakeKbd)
        hk, q, _ = _make_hk(suppress=lambda k: True, should_capture=True)
        result = hk.on_global_key_release(_FakeKey("w"))
        assert result is None
        assert q.get_nowait() == ("keyup", "w")


# ── Listener construction wires the filter on Windows only ──────────────────

class TestListenerWiring:
    def _stub_kbd(self, captured):
        class _StubListener:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            def start(self):
                pass

        return SimpleNamespace(Listener=_StubListener)

    def test_win32_wires_event_filter(self, monkeypatch):
        import services.hotkey_manager as hm
        monkeypatch.setattr(sys, "platform", "win32")
        captured: dict = {}
        monkeypatch.setattr(hm, "_keyboard_module", lambda: self._stub_kbd(captured))
        hk, _, _ = _make_hk()
        hk._start_listener()
        assert captured.get("win32_event_filter") == hk._win32_event_filter

    def test_linux_does_not_wire_event_filter(self, monkeypatch):
        import services.hotkey_manager as hm
        monkeypatch.setattr(sys, "platform", "linux")
        captured: dict = {}
        monkeypatch.setattr(hm, "_keyboard_module", lambda: self._stub_kbd(captured))
        hk, _, _ = _make_hk()
        hk._start_listener()
        assert "win32_event_filter" not in captured
