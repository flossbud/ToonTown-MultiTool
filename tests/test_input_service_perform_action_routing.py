"""Tests for TTR Perform Action routing through _send_logical_action_km.

Verifies that the new TTR-only 'action' logical action is handled by the
existing per-toon / per-keyset routing path. Also includes a run-loop
integration test asserting hold semantics (one keydown + one keyup,
autorepeats suppressed) on background TTR toons.

See docs/superpowers/specs/2026-05-26-perform-action-logical-action-design.md.
"""

import queue
import time
from unittest.mock import MagicMock

import pytest

from services.input_service import InputService
from utils import logical_actions


class _FakeKeymap:
    """In-memory keymap with TTR sets that include 'action'. Mirrors the
    shape KeymapManager exposes to _send_logical_action_km."""

    def __init__(self, sets):
        self._sets = sets

    def get_default(self, game):
        return dict(self._sets[game][0])

    def get_action_in_set(self, game, set_idx, key):
        s = self._sets[game][set_idx]
        for a in logical_actions.actions_for(game):
            if s.get(a) == key:
                return a
        return None

    def get_key_for_action(self, game, set_idx, action):
        return self._sets[game][set_idx].get(action)

    def get_all_keys(self):
        """All keys bound across all games and sets; drives
        _movement_keys() in the InputService. Mirrors the real
        KeymapManager.get_all_keys() shape."""
        keys = set()
        for game, game_sets in self._sets.items():
            for s in game_sets:
                for action in logical_actions.actions_for(game):
                    v = s.get(action)
                    if isinstance(v, str) and v:
                        keys.add(v)
        return frozenset(keys)

    def get_keys_for_game(self, game):
        """Keys bound across one game's sets. Mirrors the real
        KeymapManager.get_keys_for_game() shape (foreground-scoped)."""
        keys = set()
        for s in self._sets.get(game, []):
            for action in logical_actions.actions_for(game):
                v = s.get(action)
                if isinstance(v, str) and v:
                    keys.add(v)
        return frozenset(keys)


class _FakeWindowManager:
    def __init__(self, window_ids, active_window):
        self._wids = window_ids
        self._active = active_window

    def get_window_ids(self):
        return list(self._wids)

    def get_active_window(self):
        return self._active

    def assign_windows(self):
        pass


class _FakeRegistry:
    def __init__(self, mapping):
        self._mapping = mapping

    def get_game_for_window(self, wid):
        return self._mapping.get(str(wid))


def _make_svc(monkeypatch, sets, window_ids, active_window, assignments,
              registry_mapping, queue_obj=None):
    keymap = _FakeKeymap(sets)
    wm = _FakeWindowManager(window_ids=window_ids, active_window=active_window)
    from utils import game_registry as gr
    monkeypatch.setattr(gr.GameRegistry, "instance",
                        lambda: _FakeRegistry(registry_mapping))

    sent = []
    svc = InputService(
        window_manager=wm,
        get_enabled_toons=lambda: [True] * len(window_ids),
        get_movement_modes=lambda: ["both"] * len(window_ids),
        get_event_queue_func=lambda: queue_obj,
        settings_manager=MagicMock(),
        get_keymap_assignments=lambda: list(assignments),
        keymap_manager=keymap,
    )
    monkeypatch.setattr(
        svc, "_send_via_backend",
        lambda action, win, keysym, modifiers=None: sent.append((action, win, keysym)),
    )
    monkeypatch.setattr(svc, "_foreground_game", lambda: "ttr")
    return svc, sent


# ── Unit tests: _send_logical_action_km direct ───────────────────────────────


def test_perform_action_routes_to_bg_ttr_using_set0_binding(monkeypatch):
    """TTR1 (foreground, set 0, action=Delete), TTR2 (background, set 0).
    Press Delete. TTR2 receives Delete (set 0 outbound)."""
    sets = {
        "cc": [{"forward": "w", "reverse": "s", "left": "a", "right": "d"}],
        "ttr": [
            {"forward": "w", "reverse": "s", "left": "a", "right": "d",
             "jump": "space", "gags": "g", "tasks": "t", "book": "Alt_L",
             "map": "Shift_L", "action": "Delete"},
        ],
    }
    svc, sent = _make_svc(
        monkeypatch, sets,
        window_ids=["w1", "w2"], active_window="w1",
        assignments=[0, 0], registry_mapping={"w1": "ttr", "w2": "ttr"},
    )
    svc._send_logical_action_km("keydown", "Delete", [True, True], [0, 0])
    assert sent == [("keydown", "w2", "Delete")]


def test_perform_action_alternate_set_rebinds_input_but_outbound_stays_set0(monkeypatch):
    """Both TTR toons on set 1 (action=u). User presses u on the
    foreground toon; the bg toon receives Delete (set 0's action
    binding, which is what each toon's TTR client expects). Demonstrates
    that an alternate set can rebind the user's physical input key
    while outbound always sources from set 0, per the input-translation
    rule at input_service.py:529.

    A scenario with the bg toon on set 0 while the fg toon presses
    set 1's u would NOT route, because the strict-per-toon rule
    (verified by test_ttr_routing_per_toon_strict_same_game) means
    each toon resolves the pressed key against its own assigned set."""
    sets = {
        "cc": [{"forward": "w", "reverse": "s", "left": "a", "right": "d"}],
        "ttr": [
            {"forward": "w", "reverse": "s", "left": "a", "right": "d",
             "jump": "space", "gags": "g", "tasks": "t", "book": "Alt_L",
             "map": "Shift_L", "action": "Delete"},
            {"forward": "w", "reverse": "s", "left": "a", "right": "d",
             "jump": "space", "gags": "g", "tasks": "t", "book": "Alt_L",
             "map": "Shift_L", "action": "u"},
        ],
    }
    svc, sent = _make_svc(
        monkeypatch, sets,
        window_ids=["w1", "w2"], active_window="w1",
        assignments=[1, 1], registry_mapping={"w1": "ttr", "w2": "ttr"},
    )
    svc._send_logical_action_km("keydown", "u", [True, True], [1, 1])
    assert sent == [("keydown", "w2", "Delete")]


def test_perform_action_alternate_set_empty_falls_back_to_set0(monkeypatch):
    """TTR1 (foreground, set 0, action=Delete). TTR2 (background, set 1,
    action=''). Press Delete. Existing non-movement fallback at
    input_service.py:519-522 routes via set 0 binding -> TTR2 receives Delete.
    action is not in MOVEMENT_ACTIONS, so the fallback applies."""
    sets = {
        "cc": [{"forward": "w", "reverse": "s", "left": "a", "right": "d"}],
        "ttr": [
            {"forward": "w", "reverse": "s", "left": "a", "right": "d",
             "jump": "space", "gags": "g", "tasks": "t", "book": "Alt_L",
             "map": "Shift_L", "action": "Delete"},
            {"forward": "Up", "reverse": "Down", "left": "Left", "right": "Right",
             "jump": "space", "gags": "g", "tasks": "t", "book": "Alt_L",
             "map": "Shift_L", "action": ""},
        ],
    }
    svc, sent = _make_svc(
        monkeypatch, sets,
        window_ids=["w1", "w2"], active_window="w1",
        assignments=[0, 1], registry_mapping={"w1": "ttr", "w2": "ttr"},
    )
    svc._send_logical_action_km("keydown", "Delete", [True, True], [0, 1])
    assert sent == [("keydown", "w2", "Delete")]


def test_perform_action_global_chat_active_suppresses_all_routing(monkeypatch):
    """Chat is open; _send_logical_action_km early-returns. No action
    forwarding while typing."""
    sets = {
        "cc": [{"forward": "w", "reverse": "s", "left": "a", "right": "d"}],
        "ttr": [
            {"forward": "w", "reverse": "s", "left": "a", "right": "d",
             "jump": "space", "gags": "g", "tasks": "t", "book": "Alt_L",
             "map": "Shift_L", "action": "Delete"},
        ],
    }
    svc, sent = _make_svc(
        monkeypatch, sets,
        window_ids=["w1", "w2"], active_window="w1",
        assignments=[0, 0], registry_mapping={"w1": "ttr", "w2": "ttr"},
    )
    svc.global_chat_active = True
    svc._send_logical_action_km("keydown", "Delete", [True, True], [0, 0])
    assert sent == []


# ── Run-loop integration test: hold semantics ────────────────────────────────


def _drive(svc, q, events, settle=0.05):
    for ev in events:
        q.put(ev)
    svc.start()
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and not q.empty():
        time.sleep(0.005)
    time.sleep(settle)
    svc.stop(wait=True)


def test_holding_perform_action_sends_one_keydown_then_keyup(monkeypatch):
    """End-to-end via the run loop: holding the user's bound 'action' key
    (Delete in this test) sends exactly one keydown and one keyup to the
    background TTR toon. Autorepeat keydowns are suppressed by keys_held
    (the movement-branch dedup, not action_held; because the keymap now
    binds Delete as the 'action' logical action, the run loop routes it
    through the movement branch)."""
    sets = {
        "cc": [{"forward": "w", "reverse": "s", "left": "a", "right": "d"}],
        "ttr": [
            {"forward": "w", "reverse": "s", "left": "a", "right": "d",
             "jump": "space", "gags": "g", "tasks": "t", "book": "Alt_L",
             "map": "Shift_L", "action": "Delete"},
        ],
    }
    q = queue.Queue()
    svc, sent = _make_svc(
        monkeypatch, sets,
        window_ids=["w1", "w2"], active_window="w1",
        assignments=[0, 0], registry_mapping={"w1": "ttr", "w2": "ttr"},
        queue_obj=q,
    )

    _drive(svc, q, [
        ("keydown", "Delete"),
        ("keydown", "Delete"),  # OS autorepeat
        ("keydown", "Delete"),  # OS autorepeat
        ("keyup",   "Delete"),
    ])

    keydowns = [(a, w, k) for (a, w, k) in sent if k == "Delete" and a == "keydown"]
    keyups   = [(a, w, k) for (a, w, k) in sent if k == "Delete" and a == "keyup"]
    assert keydowns == [("keydown", "w2", "Delete")], (
        f"expected one Delete keydown on bg toon, got: {keydowns}"
    )
    assert keyups == [("keyup", "w2", "Delete")], (
        f"expected one Delete keyup on bg toon, got: {keyups}"
    )


def test_backslash_action_key_sends_keydown_and_keyup(monkeypatch):
    """Regression: when keymap stores '\\' (raw char) for the 'action' binding,
    pressing backslash must route as a held logical action to bg toons — one
    keydown then one keyup. Prior to the fix, apply_ttr_controls_to_set() stored
    'backslash' (X11 name) which pynput never delivered, causing the key to fall
    into the printable/phantom branch with no hold tracking."""
    sets = {
        "cc": [{"forward": "w", "reverse": "s", "left": "a", "right": "d"}],
        "ttr": [
            {"forward": "w", "reverse": "s", "left": "a", "right": "d",
             "jump": "space", "gags": "g", "tasks": "t", "book": "Alt_L",
             "map": "Shift_L", "action": "\\"},
        ],
    }
    q = queue.Queue()
    svc, sent = _make_svc(
        monkeypatch, sets,
        window_ids=["w1", "w2"], active_window="w1",
        assignments=[0, 0], registry_mapping={"w1": "ttr", "w2": "ttr"},
        queue_obj=q,
    )

    _drive(svc, q, [
        ("keydown", "\\"),
        ("keyup",   "\\"),
    ])

    keydowns = [(a, w, k) for (a, w, k) in sent if k == "backslash" and a == "keydown"]
    keyups   = [(a, w, k) for (a, w, k) in sent if k == "backslash" and a == "keyup"]
    assert keydowns == [("keydown", "w2", "backslash")], (
        f"expected exactly one backslash keydown on bg toon, got {keydowns} (full sent: {sent})"
    )
    assert keyups == [("keyup", "w2", "backslash")], (
        f"expected exactly one backslash keyup on bg toon, got {keyups} (full sent: {sent})"
    )


def test_perform_action_falls_into_movement_branch_not_action_held(monkeypatch):
    """Regression guard: once Delete is bound as the 'action' logical
    action in the keymap, _movement_keys() includes it and the run loop
    routes it through the movement branch (keys_held). It must NOT enter
    the legacy non-printable catch-all (action_held). action_held stays
    empty after pressing Delete."""
    sets = {
        "cc": [{"forward": "w", "reverse": "s", "left": "a", "right": "d"}],
        "ttr": [
            {"forward": "w", "reverse": "s", "left": "a", "right": "d",
             "jump": "space", "gags": "g", "tasks": "t", "book": "Alt_L",
             "map": "Shift_L", "action": "Delete"},
        ],
    }
    q = queue.Queue()
    svc, _sent = _make_svc(
        monkeypatch, sets,
        window_ids=["w1", "w2"], active_window="w1",
        assignments=[0, 0], registry_mapping={"w1": "ttr", "w2": "ttr"},
        queue_obj=q,
    )

    q.put(("keydown", "Delete"))
    svc.start()
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and "Delete" not in svc.keys_held:
        time.sleep(0.005)
    try:
        assert "Delete" in svc.keys_held, (
            "Delete should ride the movement branch via keys_held, "
            "not the action_held catch-all"
        )
        assert "Delete" not in svc.action_held, (
            "Delete must not be in action_held; the keymap binds it as "
            "the 'action' logical action so _movement_keys() includes it"
        )
    finally:
        svc.stop(wait=True)
