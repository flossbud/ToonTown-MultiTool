"""Tests for the macOS darwin_intercept suppression path in HotkeyManager.

The darwin interceptor is SUPPRESS-ONLY (amendment C): it decides whether to
suppress an event at the OS level (return None) or pass it through (return the
event). It must NEVER enqueue, because on_global_key_press/on_global_key_release
remain the single enqueue point and pynput fires them even for events the
interceptor suppresses. Every test below therefore also asserts the queue stays
EMPTY.

Suppression is additionally gated on the event's target PID (amendment D): only
suppress when the event targets a known game PID. A 0/absent target PID, or an
empty known-PID set, falls back to the suppress decision (under-suppression is
the safer failure; we never over-suppress and eat typing in unrelated apps).

Run: TTMT_NO_VENV_REEXEC=1 QT_QPA_PLATFORM=offscreen pytest tests/test_hotkey_manager_darwin.py -v
"""
from __future__ import annotations

import queue
import sys

import pytest

from services.hotkey_manager import HotkeyManager


# CGKeyCodes used by the tests (from utils.macos_keycodes).
KC_W = 0x0D       # -> "w"
KC_UNMAPPED = 0xFF  # not in the translation table -> keysym None


# ── Fake Quartz ──────────────────────────────────────────────────────────────
# A dict-backed event + a minimal Quartz surface exposing exactly the constants
# and functions _darwin_intercept touches.

class FakeQuartz:
    # Event types
    kCGEventKeyDown = 10
    kCGEventKeyUp = 11
    kCGEventTapDisabledByTimeout = 0xFFFFFFFE
    kCGEventTapDisabledByUserInput = 0xFFFFFFFF

    # Integer value field selectors
    kCGKeyboardEventKeycode = 9
    kCGEventTargetUnixProcessID = 39

    def __init__(self):
        self.tap_enable_calls = []  # list of (tap, on_bool)

    def CGEventGetIntegerValueField(self, ev, field):
        # ev is a dict mapping field-selector -> value.
        return ev[field]

    def CGEventTapEnable(self, tap, on):
        self.tap_enable_calls.append((tap, on))


def _event(keycode=None, target_pid=None):
    ev = {}
    if keycode is not None:
        ev[FakeQuartz.kCGKeyboardEventKeycode] = keycode
    if target_pid is not None:
        ev[FakeQuartz.kCGEventTargetUnixProcessID] = target_pid
    return ev


class _StubListenerWithTap:
    def __init__(self):
        self._tap = object()


def _make_hk(quartz, *, suppress_predicate=None, game_pids=frozenset(), listener=None):
    """Build a bare HotkeyManager (no full app) wired only with what the
    interceptor reads, and a fake Quartz."""
    hk = HotkeyManager.__new__(HotkeyManager)
    hk.key_event_queue = queue.Queue()
    hk.suppress_predicate = suppress_predicate
    hk._darwin_game_pids = game_pids
    hk.listener = listener
    hk._quartz_for_intercept = lambda: quartz
    return hk


# ── _darwin_intercept: suppress-only + target-PID gate ───────────────────────

class TestDarwinIntercept:
    def test_suppressed_game_key_targeting_game_pid_is_suppressed(self):
        q = FakeQuartz()
        hk = _make_hk(q, suppress_predicate=lambda ks: True, game_pids=frozenset({101}))
        ev = _event(keycode=KC_W, target_pid=101)
        assert hk._darwin_intercept(q.kCGEventKeyDown, ev) is None  # suppress
        assert hk.key_event_queue.empty()  # amendment C: never enqueues

    def test_non_grabbed_key_passes_through(self):
        q = FakeQuartz()
        hk = _make_hk(q, suppress_predicate=lambda ks: False, game_pids=frozenset({101}))
        ev = _event(keycode=KC_W, target_pid=101)
        assert hk._darwin_intercept(q.kCGEventKeyDown, ev) is ev  # pass through
        assert hk.key_event_queue.empty()

    def test_target_pid_gate_blocks_suppression_for_non_game_pid(self):
        q = FakeQuartz()
        hk = _make_hk(q, suppress_predicate=lambda ks: True, game_pids=frozenset({101}))
        ev = _event(keycode=KC_W, target_pid=999)  # non-game target
        assert hk._darwin_intercept(q.kCGEventKeyDown, ev) is ev  # NOT suppressed
        assert hk.key_event_queue.empty()

    def test_target_pid_zero_falls_back_to_suppress(self):
        q = FakeQuartz()
        hk = _make_hk(q, suppress_predicate=lambda ks: True, game_pids=frozenset({101}))
        ev = _event(keycode=KC_W, target_pid=0)
        assert hk._darwin_intercept(q.kCGEventKeyDown, ev) is None  # suppress
        assert hk.key_event_queue.empty()

    def test_empty_game_pid_set_falls_back_to_suppress(self):
        q = FakeQuartz()
        hk = _make_hk(q, suppress_predicate=lambda ks: True, game_pids=frozenset())
        ev = _event(keycode=KC_W, target_pid=12345)  # any target
        assert hk._darwin_intercept(q.kCGEventKeyDown, ev) is None  # suppress
        assert hk.key_event_queue.empty()

    def test_unmapped_keycode_passes_through(self):
        q = FakeQuartz()
        hk = _make_hk(q, suppress_predicate=lambda ks: True, game_pids=frozenset({101}))
        ev = _event(keycode=KC_UNMAPPED, target_pid=101)
        assert hk._darwin_intercept(q.kCGEventKeyDown, ev) is ev  # pass through
        assert hk.key_event_queue.empty()

    def test_no_suppress_predicate_passes_through(self):
        q = FakeQuartz()
        hk = _make_hk(q, suppress_predicate=None, game_pids=frozenset({101}))
        ev = _event(keycode=KC_W, target_pid=101)
        assert hk._darwin_intercept(q.kCGEventKeyDown, ev) is ev  # pass through
        assert hk.key_event_queue.empty()

    def test_keyup_of_suppressed_key_targeting_game_pid_is_suppressed(self):
        q = FakeQuartz()
        hk = _make_hk(q, suppress_predicate=lambda ks: True, game_pids=frozenset({101}))
        ev = _event(keycode=KC_W, target_pid=101)
        assert hk._darwin_intercept(q.kCGEventKeyUp, ev) is None  # suppress
        assert hk.key_event_queue.empty()  # still never enqueues


# ── Tap-health: re-enable a disabled tap ─────────────────────────────────────

class TestTapDisabledReenable:
    def test_tap_disabled_passes_event_and_reenables_tap(self):
        q = FakeQuartz()
        listener = _StubListenerWithTap()
        hk = _make_hk(q, suppress_predicate=lambda ks: True, listener=listener)
        ev = _event(keycode=KC_W, target_pid=101)
        result = hk._darwin_intercept(q.kCGEventTapDisabledByTimeout, ev)
        assert result is ev  # tap-disabled events always pass through
        assert q.tap_enable_calls == [(listener._tap, True)]
        assert hk.key_event_queue.empty()

    def test_tap_disabled_without_tap_is_safe(self):
        q = FakeQuartz()
        hk = _make_hk(q, suppress_predicate=lambda ks: True, listener=None)
        ev = _event(keycode=KC_W, target_pid=101)
        result = hk._darwin_intercept(q.kCGEventTapDisabledByUserInput, ev)
        assert result is ev
        assert q.tap_enable_calls == []  # no _tap to re-enable
        assert hk.key_event_queue.empty()


# ── _refresh_darwin_game_pids ────────────────────────────────────────────────

class _FakeRecord:
    def __init__(self, pid):
        self.pid = pid


class TestRefreshDarwinGamePids:
    def test_refresh_on_darwin_populates_from_discovery(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        from utils import macos_discovery
        monkeypatch.setattr(
            macos_discovery, "_enumerate_game_windows",
            lambda: [_FakeRecord(101), _FakeRecord(202)],
        )
        hk = HotkeyManager.__new__(HotkeyManager)
        hk._darwin_game_pids = frozenset()
        hk._refresh_darwin_game_pids()
        assert hk._darwin_game_pids == frozenset({101, 202})

    def test_refresh_off_darwin_stays_empty(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        hk = HotkeyManager.__new__(HotkeyManager)
        hk._darwin_game_pids = frozenset()
        hk._refresh_darwin_game_pids()
        assert hk._darwin_game_pids == frozenset()

    def test_refresh_swallows_discovery_error(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        from utils import macos_discovery

        def _boom():
            raise RuntimeError("window server unavailable")

        monkeypatch.setattr(macos_discovery, "_enumerate_game_windows", _boom)
        hk = HotkeyManager.__new__(HotkeyManager)
        hk._darwin_game_pids = frozenset({999})
        hk._refresh_darwin_game_pids()
        assert hk._darwin_game_pids == frozenset()
