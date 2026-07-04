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
    kCGEventFlagsChanged = 12      # modifier press/release (in the keyboard tap mask)
    NSSystemDefined = 14           # media / special keys (in the keyboard tap mask)
    kCGEventTapDisabledByTimeout = 0xFFFFFFFE
    kCGEventTapDisabledByUserInput = 0xFFFFFFFF

    # Integer value field selectors
    kCGKeyboardEventKeycode = 9
    kCGEventTargetUnixProcessID = 39
    kCGKeyboardEventAutorepeat = 8

    def __init__(self):
        self.tap_enable_calls = []  # list of (tap, on_bool)

    def CGEventGetIntegerValueField(self, ev, field):
        # ev is a dict mapping field-selector -> value.
        return ev[field]

    def CGEventTapEnable(self, tap, on):
        self.tap_enable_calls.append((tap, on))


def _event(keycode=None, target_pid=None, autorepeat=None):
    ev = {}
    if keycode is not None:
        ev[FakeQuartz.kCGKeyboardEventKeycode] = keycode
    if target_pid is not None:
        ev[FakeQuartz.kCGEventTargetUnixProcessID] = target_pid
    if autorepeat is not None:
        ev[FakeQuartz.kCGKeyboardEventAutorepeat] = autorepeat
    return ev


def _make_hk(quartz, *, suppress_predicate=None, game_pids=frozenset(), listener=None):
    """Build a bare HotkeyManager (no full app) wired only with what the
    interceptor reads, and a fake Quartz."""
    hk = HotkeyManager.__new__(HotkeyManager)
    hk.key_event_queue = queue.Queue()
    hk.suppress_predicate = suppress_predicate
    hk._darwin_game_pids = game_pids
    hk.listener = listener
    hk._quartz_for_intercept = lambda: quartz
    hk._suppressed_down = set()
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

    def test_absent_target_pid_field_falls_back_to_suppress(self):
        # The target-PID field may not be populated at the tap (the plan flags
        # this as a live risk). FakeQuartz raises KeyError on the missing field;
        # the interceptor must treat that as target_pid=0 and fall back to
        # suppress, never raise into the tap thread.
        q = FakeQuartz()
        hk = _make_hk(q, suppress_predicate=lambda ks: True, game_pids=frozenset({101}))
        ev = _event(keycode=KC_W)  # no target_pid field at all
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

    def test_keyup_without_suppressed_keydown_passes_through(self):
        # Pairing law: a release whose press the OS delivered must be
        # delivered too, no matter what the CURRENT grab state says. Deciding
        # the keyup from current state ate the release of a key held across a
        # state flip and left the focused client holding it forever (the
        # stuck-movement-key class).
        q = FakeQuartz()
        hk = _make_hk(q, suppress_predicate=lambda ks: True, game_pids=frozenset({101}))
        ev = _event(keycode=KC_W, target_pid=101)
        assert hk._darwin_intercept(q.kCGEventKeyUp, ev) is ev  # pass through
        assert hk.key_event_queue.empty()  # still never enqueues

    def test_raising_suppress_predicate_fails_open(self):
        # A suppress predicate that raises must NEVER propagate into the pynput
        # tap thread (that would silently kill capture). The interceptor is
        # fail-open: on any error it passes the event through.
        def _boom(_ks):
            raise RuntimeError("grabber exploded")

        q = FakeQuartz()
        hk = _make_hk(q, suppress_predicate=_boom, game_pids=frozenset({101}))
        ev = _event(keycode=KC_W, target_pid=101)
        assert hk._darwin_intercept(q.kCGEventKeyDown, ev) is ev  # passed through
        assert hk.key_event_queue.empty()


# ── Keyup pairing: the initial keydown's decision owns the hold ──────────────
# The win32 _suppressed_down analog, hardened with repeat-inherit: autorepeat
# keydowns and the keyup follow the INITIAL (non-repeat) keydown's suppress
# decision, so the OS/client can never see a half-delivered hold (down without
# up, or up without down) when grab state flips mid-hold.

class TestDarwinKeyupPairing:
    def _down_up(self, hk, q, *, target_pid=101):
        down = _event(keycode=KC_W, target_pid=target_pid)
        up = _event(keycode=KC_W, target_pid=target_pid)
        return (hk._darwin_intercept(q.kCGEventKeyDown, down),
                hk._darwin_intercept(q.kCGEventKeyUp, up))

    def test_suppressed_down_pairs_suppressed_up(self):
        q = FakeQuartz()
        hk = _make_hk(q, suppress_predicate=lambda ks: True, game_pids=frozenset({101}))
        d, u = self._down_up(hk, q)
        assert d is None and u is None
        assert hk._suppressed_down == set()  # entry consumed by the release
        assert hk.key_event_queue.empty()

    def test_native_down_keeps_native_up_even_after_state_flip(self):
        # The stuck-movement-key scenario: down delivered natively (grabs off,
        # e.g. during chat), state flips to suppressing mid-hold (chat closed,
        # grabs reinstalled), release must STILL pass or the client strands
        # the key down.
        q = FakeQuartz()
        state = {"suppress": False}
        hk = _make_hk(q, suppress_predicate=lambda ks: state["suppress"],
                      game_pids=frozenset({101}))
        down = _event(keycode=KC_W, target_pid=101)
        assert hk._darwin_intercept(q.kCGEventKeyDown, down) is down
        state["suppress"] = True  # mid-hold flip
        up = _event(keycode=KC_W, target_pid=101)
        assert hk._darwin_intercept(q.kCGEventKeyUp, up) is up  # delivered
        assert hk.key_event_queue.empty()

    def test_suppressed_down_pairs_suppressed_up_after_state_flip(self):
        # Mirror image: down withheld, grabs uninstalled mid-hold, release
        # must STILL be withheld (the client never saw the down).
        q = FakeQuartz()
        state = {"suppress": True}
        hk = _make_hk(q, suppress_predicate=lambda ks: state["suppress"],
                      game_pids=frozenset({101}))
        down = _event(keycode=KC_W, target_pid=101)
        assert hk._darwin_intercept(q.kCGEventKeyDown, down) is None
        state["suppress"] = False  # mid-hold flip
        up = _event(keycode=KC_W, target_pid=101)
        assert hk._darwin_intercept(q.kCGEventKeyUp, up) is None  # withheld
        assert hk.key_event_queue.empty()

    def test_autorepeat_inherits_native_hold_and_never_pollutes_pairing(self):
        # The hole the win32 shape still has: a native hold's autorepeat
        # arriving after a mid-hold flip must NOT re-decide suppression (that
        # would enter the pairing set and eat the release of a key the client
        # received natively).
        q = FakeQuartz()
        state = {"suppress": False}
        hk = _make_hk(q, suppress_predicate=lambda ks: state["suppress"],
                      game_pids=frozenset({101}))
        down = _event(keycode=KC_W, target_pid=101)
        assert hk._darwin_intercept(q.kCGEventKeyDown, down) is down  # native
        state["suppress"] = True  # mid-hold flip
        rep = _event(keycode=KC_W, target_pid=101, autorepeat=1)
        assert hk._darwin_intercept(q.kCGEventKeyDown, rep) is rep  # inherited
        assert hk._suppressed_down == set()
        up = _event(keycode=KC_W, target_pid=101)
        assert hk._darwin_intercept(q.kCGEventKeyUp, up) is up  # delivered
        assert hk.key_event_queue.empty()

    def test_autorepeat_inherits_suppressed_hold(self):
        q = FakeQuartz()
        state = {"suppress": True}
        hk = _make_hk(q, suppress_predicate=lambda ks: state["suppress"],
                      game_pids=frozenset({101}))
        down = _event(keycode=KC_W, target_pid=101)
        assert hk._darwin_intercept(q.kCGEventKeyDown, down) is None
        state["suppress"] = False  # mid-hold flip
        rep = _event(keycode=KC_W, target_pid=101, autorepeat=1)
        assert hk._darwin_intercept(q.kCGEventKeyDown, rep) is None  # inherited
        up = _event(keycode=KC_W, target_pid=101)
        assert hk._darwin_intercept(q.kCGEventKeyUp, up) is None  # paired
        assert hk.key_event_queue.empty()

    def test_fresh_native_down_clears_stale_pairing_entry(self):
        # A release lost while the tap was down leaves a stale entry; the next
        # physical press decides fresh and must supersede it, or this hold's
        # real release would be eaten.
        q = FakeQuartz()
        hk = _make_hk(q, suppress_predicate=lambda ks: False,
                      game_pids=frozenset({101}))
        hk._suppressed_down.add("w")  # stale
        down = _event(keycode=KC_W, target_pid=101)
        assert hk._darwin_intercept(q.kCGEventKeyDown, down) is down
        assert "w" not in hk._suppressed_down
        assert hk.key_event_queue.empty()

    def test_pid_gate_veto_leaves_no_pairing_entry(self):
        q = FakeQuartz()
        hk = _make_hk(q, suppress_predicate=lambda ks: True, game_pids=frozenset({101}))
        down = _event(keycode=KC_W, target_pid=999)  # non-game target
        assert hk._darwin_intercept(q.kCGEventKeyDown, down) is down
        assert hk._suppressed_down == set()
        up = _event(keycode=KC_W, target_pid=999)
        assert hk._darwin_intercept(q.kCGEventKeyUp, up) is up
        assert hk.key_event_queue.empty()


# ── Non-key events pass through untouched ────────────────────────────────────
# pynput's keyboard tap also delivers flagsChanged (modifiers), NSSystemDefined
# (media) and tap-disabled notifications. The interceptor only runs the suppress
# logic for key-down/up; everything else passes through and is never re-enabled
# or suppressed (pynput 1.8 does not expose the tap to re-enable, and recovery
# happens when the listener restarts on a focus change).

class TestNonKeyEventsPassThrough:
    def test_flags_changed_event_passes_through(self):
        q = FakeQuartz()
        hk = _make_hk(q, suppress_predicate=lambda ks: True, game_pids=frozenset({101}))
        ev = _event(keycode=KC_W, target_pid=101)  # keycode is irrelevant for non-key types
        assert hk._darwin_intercept(q.kCGEventFlagsChanged, ev) is ev
        assert hk.key_event_queue.empty()

    def test_system_defined_event_passes_through(self):
        q = FakeQuartz()
        hk = _make_hk(q, suppress_predicate=lambda ks: True, game_pids=frozenset({101}))
        ev = _event(keycode=KC_W, target_pid=101)
        assert hk._darwin_intercept(q.NSSystemDefined, ev) is ev
        assert hk.key_event_queue.empty()

    def test_tap_disabled_event_passes_through_without_reenable(self):
        # pynput 1.8 keeps its tap as a local and does not expose it, so the
        # interceptor cannot (and must not pretend to) re-enable it. It simply
        # passes the notification through; recovery is via listener restart.
        q = FakeQuartz()
        hk = _make_hk(q, suppress_predicate=lambda ks: True, game_pids=frozenset({101}))
        ev = _event(keycode=KC_W, target_pid=101)
        assert hk._darwin_intercept(q.kCGEventTapDisabledByTimeout, ev) is ev
        assert q.tap_enable_calls == []  # no bogus re-enable attempt
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


class _FakeWM:
    def __init__(self, *, capture: bool, has_windows: bool):
        self._capture = capture
        self._has = has_windows

    def should_capture_input(self) -> bool:
        return self._capture

    def has_game_windows(self) -> bool:
        return self._has


class TestDarwinListenerKeepAlive:
    """darwin lifecycle rule (live 2026-07-04): the ACTIVE keyboard tap must
    not churn on game-focus edges - teardown/recreation stalls the SYSTEM
    keyboard stream. While any game window EXISTS the listener stays up even
    when capture is off (per-event gates keep unfocused keys passthrough)."""

    def _mk(self, monkeypatch, platform, capture, has_windows):
        monkeypatch.setattr(sys, "platform", platform)
        hk = HotkeyManager.__new__(HotkeyManager)
        hk.window_manager = _FakeWM(capture=capture, has_windows=has_windows)
        hk.is_listening = False
        hk._darwin_game_pids = frozenset()
        hk.calls = []
        hk._refresh_darwin_game_pids = lambda: hk.calls.append("refresh")
        hk._start_listener = lambda: hk.calls.append("start")
        hk._stop_listener = lambda: hk.calls.append("stop")
        return hk

    def test_darwin_unfocused_with_game_windows_keeps_listener(self, monkeypatch):
        hk = self._mk(monkeypatch, "darwin", capture=False, has_windows=True)
        hk._on_active_window_changed("")
        assert hk.calls[-1] == "start"

    def test_darwin_unfocused_without_game_windows_stops(self, monkeypatch):
        hk = self._mk(monkeypatch, "darwin", capture=False, has_windows=False)
        hk._on_active_window_changed("")
        assert hk.calls[-1] == "stop"

    def test_darwin_focused_still_starts_and_refreshes_pids(self, monkeypatch):
        hk = self._mk(monkeypatch, "darwin", capture=True, has_windows=True)
        hk._on_active_window_changed("123")
        assert hk.calls == ["refresh", "start"]

    def test_off_darwin_lifecycle_unchanged(self, monkeypatch):
        hk = self._mk(monkeypatch, "linux", capture=False, has_windows=True)
        hk._on_active_window_changed("")
        assert hk.calls[-1] == "stop"


class TestDarwinSelfFocusTapLifecycle:
    """Self-focused capture (TTMT frontmost) must NOT create a tap when no
    game windows exist: it would be torn down on the very next focus-out -
    the exact churn class the keep-alive rule outlaws. With games up, the
    listener is already alive and self-focus rides it. No-game global
    hotkeys are the Carbon provider's job (no tap)."""

    def _mk(self, monkeypatch, platform, capture, has_windows):
        monkeypatch.setattr(sys, "platform", platform)
        hk = HotkeyManager.__new__(HotkeyManager)
        hk.window_manager = _FakeWM(capture=capture, has_windows=has_windows)
        hk.is_listening = False
        hk._darwin_game_pids = frozenset()
        hk.calls = []
        hk._refresh_darwin_game_pids = lambda: hk.calls.append("refresh")
        hk._start_listener = lambda: hk.calls.append("start")
        hk._stop_listener = lambda: hk.calls.append("stop")
        return hk

    def test_darwin_self_focus_without_games_does_not_start_tap(self, monkeypatch):
        hk = self._mk(monkeypatch, "darwin", capture=True, has_windows=False)
        hk._on_active_window_changed("")
        assert hk.calls == ["refresh", "stop"]

    def test_darwin_self_focus_with_games_keeps_listener(self, monkeypatch):
        hk = self._mk(monkeypatch, "darwin", capture=True, has_windows=True)
        hk._on_active_window_changed("")
        assert hk.calls == ["refresh", "start"]

    def test_win32_self_focus_starts_listener(self, monkeypatch):
        # win32 has no keep-alive/tap-churn constraint; self-focused capture
        # starts the LL-hook listener directly (Linux-parity hotkeys while
        # the tool is frontmost).
        hk = self._mk(monkeypatch, "win32", capture=True, has_windows=False)
        hk._on_active_window_changed("")
        assert hk.calls == ["start"]


class TestProviderModeTapFallback:
    """CP9(b): with the Carbon provider armed, the tap fires ONLY what
    Carbon can never see - chords whose key the intercept suppressed at the
    OS (the session tap PRECEDES Carbon dispatch) and two-key chords
    (RegisterEventHotKey is single-key+modifiers). Every other match is
    still SKIPPED from the input queue (Carbon owns the fire)."""

    def _mk(self, hook):
        import queue as _queue
        from unittest.mock import MagicMock
        wm = MagicMock()
        wm.should_capture_input.return_value = True
        q = _queue.Queue(maxsize=10)
        hm = HotkeyManager(wm, q, hotkey_hook=hook, fire_hotkeys=True)
        hm.set_hotkey_provider_armed(True)
        seen = []
        hm.hotkey_triggered.connect(seen.append)
        return hm, q, seen

    def _key(self, char):
        from unittest.mock import MagicMock
        k = MagicMock()
        k.char = char
        k.name = None
        k.vk = None
        return k

    def test_armed_flips_fire_and_fallback(self):
        from unittest.mock import MagicMock
        import queue as _queue
        wm = MagicMock()
        wm.should_capture_input.return_value = True
        hm = HotkeyManager(wm, _queue.Queue(), fire_hotkeys=True)
        assert hm._fire_hotkeys is True and hm._hotkey_tap_fallback is False
        hm.set_hotkey_provider_armed(True)
        assert hm._fire_hotkeys is False and hm._hotkey_tap_fallback is True
        hm.set_hotkey_provider_armed(False)
        assert hm._fire_hotkeys is True and hm._hotkey_tap_fallback is False

    def test_visible_chord_skips_queue_but_does_not_fire(self):
        # Carbon sees this chord (not suppressed, single-key): the tap must
        # not double-fire it, but the match must still never enqueue.
        hm, q, seen = self._mk(
            lambda mods, keys: "act" if keys == frozenset({"h"}) else None)
        hm.on_global_key_press(self._key("h"))
        assert seen == []
        assert q.empty()

    def test_suppressed_chord_fires_tap_side(self):
        # The intercept ate this key at the OS (route_all grab): Carbon can
        # never see it, so the tap owns the dispatch.
        hm, q, seen = self._mk(
            lambda mods, keys: "act" if keys == frozenset({"h"}) else None)
        hm._suppressed_down.add("h")
        hm.on_global_key_press(self._key("h"))
        assert seen == ["act"]
        assert q.empty()

    def test_two_key_chord_fires_tap_side(self):
        # Not representable by RegisterEventHotKey: always tap-side.
        hm, q, seen = self._mk(
            lambda mods, keys: "pair" if keys == frozenset({"g", "h"})
            else None)
        hm.on_global_key_press(self._key("g"))   # first member: normal enqueue
        assert q.qsize() == 1
        hm.on_global_key_press(self._key("h"))   # full-set match
        assert seen == ["pair"]
        assert q.qsize() == 1                    # the match never enqueued
