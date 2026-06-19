"""Focused-toon synth must not double-deliver keys the grabber did NOT suppress.

Bug (macOS/Win32): _send_logical_action_km synthesizes the focused toon's key to
the FOCUSED window whenever strict TTR is globally active, assuming route_all
suppressed the native key. But the macOS/Win32 grab is NON-EXCLUSIVE: it only
suppresses the movement keyset (wasd/arrows). Action keys that map to a logical
action but are not in the suppressed set (jump=space, tasks=t) reach the focused
window natively AND get re-synthesized -> the focused toon receives them twice.
wasd are suppressed, so only the synth survives -> single. This is why "space
and t double, wasd do not" on macOS.

Fix: gate the focused-toon synth on whether the key was ACTUALLY suppressed.
A full-grab grabber (X11, needs_focused_passthrough=True) withholds every key,
so synth-all stays correct there; a non-exclusive grabber only withholds keys
should_suppress() returns True for.
"""
import queue
from unittest.mock import MagicMock

import pytest

from services.input_service import InputService


class _WM:
    def __init__(self, active="100", ids=("100", "200")):
        self._active = active
        self._ids = list(ids)

    def get_active_window(self):
        return self._active

    def get_window_ids(self):
        return list(self._ids)

    def assign_windows(self):
        pass


class _Grabber:
    """Fake movement grabber. needs_focused_passthrough mirrors the platform
    grabbers: False = non-exclusive (macOS/Win32), True = full grab (X11)."""

    def __init__(self, needs_focused_passthrough, suppressed=()):
        self.needs_focused_passthrough = needs_focused_passthrough
        self._suppressed = set(suppressed)

    def should_suppress(self, keysym):
        return keysym in self._suppressed


_MOVEMENT = ("w", "a", "s", "d", "Up", "Down", "Left", "Right")
# key -> logical action ; action -> default (set 0) outbound key
_ACTION_FOR_KEY = {"w": "forward", "space": "jump", "t": "tasks"}
_OUTBOUND_FOR_ACTION = {"forward": "w", "jump": "space", "tasks": "t"}


def _make_svc(monkeypatch, grabber, active="100", ids=("100", "200")):
    reg = MagicMock()
    reg.get_game_for_window.side_effect = lambda wid: "ttr"
    monkeypatch.setattr("utils.game_registry.GameRegistry.instance", lambda: reg)
    # logical_actions.supports is imported inside _send_logical_action_km.
    monkeypatch.setattr("utils.logical_actions.supports", lambda game, action: True)

    km = MagicMock()
    km.get_action_in_set.side_effect = lambda game, set_idx, key: _ACTION_FOR_KEY.get(key)
    km.get_key_for_action.side_effect = lambda game, set_idx, action: _OUTBOUND_FOR_ACTION.get(action)
    km.get_keys_for_game.side_effect = lambda game: frozenset(_ACTION_FOR_KEY)

    svc = InputService(
        window_manager=_WM(active=active, ids=ids),
        get_enabled_toons=lambda: [True, True],
        get_movement_modes=lambda: ["both", "both"],
        get_event_queue_func=lambda: queue.Queue(),
        settings_manager=MagicMock(get=lambda *a, **k: True),
        get_keymap_assignments=lambda: [0, 0],
        keymap_manager=km,
    )
    svc._key_grabber = grabber
    svc._strict_ttr_active = lambda: True
    svc._strict_drain_active = False
    svc._resolve_keysym = lambda k: k
    svc._note_blocked_movement = lambda *a, **k: None
    sends = []
    svc._send_via_backend = lambda action, win, keysym, modifiers=None: sends.append(
        (action, str(win), keysym)
    )
    return svc, sends


def _focused(sends, wid="100"):
    return [c for c in sends if c[1] == wid]


# ── macOS / Win32 (non-exclusive grab) ───────────────────────────────────────

def test_unsuppressed_action_key_not_synthesized_to_focused(monkeypatch):
    # space=jump is NOT in the suppressed set -> it reaches the focused window
    # natively, so it must NOT be re-synthesized (that is the double).
    grabber = _Grabber(needs_focused_passthrough=False, suppressed=_MOVEMENT)
    svc, sends = _make_svc(monkeypatch, grabber)
    svc._send_logical_action_km("keydown", "space", [True, True], [0, 0])
    assert _focused(sends, "100") == []          # no double on the focused toon


def test_suppressed_movement_key_still_synthesized_to_focused(monkeypatch):
    # w=forward IS suppressed natively -> the synth is its only delivery; keep it.
    grabber = _Grabber(needs_focused_passthrough=False, suppressed=_MOVEMENT)
    svc, sends = _make_svc(monkeypatch, grabber)
    svc._send_logical_action_km("keydown", "w", [True, True], [0, 0])
    assert _focused(sends, "100") == [("keydown", "100", "w")]


def test_keyup_mirrors_keydown_for_focused_synth(monkeypatch):
    grabber = _Grabber(needs_focused_passthrough=False, suppressed=_MOVEMENT)
    svc, sends = _make_svc(monkeypatch, grabber)
    svc._send_logical_action_km("keyup", "space", [True, True], [0, 0])
    assert _focused(sends, "100") == []          # space keyup also skipped
    sends.clear()
    svc._send_logical_action_km("keyup", "w", [True, True], [0, 0])
    assert _focused(sends, "100") == [("keyup", "100", "w")]


def test_background_toon_forwarding_unchanged_for_unsuppressed_key(monkeypatch):
    # The fix only affects the FOCUSED toon; background toons still get the key.
    grabber = _Grabber(needs_focused_passthrough=False, suppressed=_MOVEMENT)
    svc, sends = _make_svc(monkeypatch, grabber)
    svc._send_logical_action_km("keydown", "space", [True, True], [0, 0])
    assert _focused(sends, "200") == [("keydown", "200", "space")]


# ── X11 (full grab) must be unaffected ───────────────────────────────────────

def test_full_grab_grabber_still_synthesizes_unsuppressed_key_to_focused(monkeypatch):
    # X11's active grab withholds EVERY key from the focused window, so the synth
    # remains required for all keys (no should_suppress consulted).
    grabber = _Grabber(needs_focused_passthrough=True)  # full grab
    svc, sends = _make_svc(monkeypatch, grabber)
    svc._send_logical_action_km("keydown", "space", [True, True], [0, 0])
    assert _focused(sends, "100") == [("keydown", "100", "space")]
