"""Hold-duration mirror tests for InputService.

Drives keydown -> sleep T -> keyup through the event queue for each held-
key shape (movement, Space/jump, Perform Action, F-key, modifier) and
asserts that the bg toon's backend received exactly one keydown and one
keyup whose timestamps are at least HOLD_SECONDS apart (within tolerance
for scheduler / autorepeat-dedup jitter). Locks in the contract that
underpins TTR mechanics like pie-throw charge time and Cog stunning.

See docs/superpowers/specs/2026-05-26-held-key-registry-design.md.
"""

import queue
import time
from unittest.mock import MagicMock

import pytest

from services.input_service import InputService
from utils import logical_actions


HOLD_SECONDS = 0.30
TOLERANCE   = 0.05


class _FakeKeymap:
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
        keys = set()
        for game, game_sets in self._sets.items():
            for s in game_sets:
                for action in logical_actions.actions_for(game):
                    v = s.get(action)
                    if isinstance(v, str) and v:
                        keys.add(v)
        return frozenset(keys)

    def get_keys_for_game(self, game):
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
              registry_mapping, queue_obj):
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

    def _record(action, win, keysym, modifiers=None):
        sent.append((time.monotonic(), action, win, keysym))

    monkeypatch.setattr(svc, "_send_via_backend", _record)
    monkeypatch.setattr(svc, "_foreground_game", lambda: "ttr")
    return svc, sent


def _ttr_sets_with_action_delete():
    return {
        "cc": [{"forward": "w", "reverse": "s", "left": "a", "right": "d"}],
        "ttr": [
            {"forward": "w", "reverse": "s", "left": "a", "right": "d",
             "jump": "space", "gags": "g", "tasks": "t", "book": "Alt_L",
             "map": "Shift_L", "action": "Delete"},
        ],
    }


def _start_and_drain(svc, q, hold_seconds, keydown_event, keyup_event):
    svc.start()
    try:
        q.put(keydown_event)
        time.sleep(hold_seconds)
        q.put(keyup_event)
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline and not q.empty():
            time.sleep(0.005)
        time.sleep(0.08)
    finally:
        svc.stop(wait=True)


def _measure_hold(sent, keysym, win):
    keydowns = [(t, a, w, k) for (t, a, w, k) in sent if a == "keydown" and k == keysym and w == win]
    keyups   = [(t, a, w, k) for (t, a, w, k) in sent if a == "keyup"   and k == keysym and w == win]
    return keydowns, keyups


def test_holding_perform_action_mirrors_duration_on_bg_toon(monkeypatch):
    """Hold Delete (action) for HOLD_SECONDS; bg toon receives one
    keydown at T1 and one keyup at T2 with (T2 - T1) >= HOLD_SECONDS - TOLERANCE."""
    q = queue.Queue()
    svc, sent = _make_svc(
        monkeypatch, _ttr_sets_with_action_delete(),
        window_ids=["w1", "w2"], active_window="w1",
        assignments=[0, 0], registry_mapping={"w1": "ttr", "w2": "ttr"},
        queue_obj=q,
    )
    _start_and_drain(svc, q, HOLD_SECONDS,
                     ("keydown", "Delete"), ("keyup", "Delete"))
    keydowns, keyups = _measure_hold(sent, "Delete", "w2")
    assert len(keydowns) == 1, f"expected 1 keydown, got {len(keydowns)}: {keydowns}"
    assert len(keyups) == 1, f"expected 1 keyup, got {len(keyups)}: {keyups}"
    measured = keyups[0][0] - keydowns[0][0]
    assert measured >= HOLD_SECONDS - TOLERANCE, (
        f"bg toon hold duration {measured:.3f}s did not mirror "
        f"user hold {HOLD_SECONDS:.3f}s (tolerance {TOLERANCE:.3f}s)"
    )


def test_holding_space_jump_mirrors_duration_on_bg_toon(monkeypatch):
    """Same as above but for Space (logical 'jump')."""
    q = queue.Queue()
    svc, sent = _make_svc(
        monkeypatch, _ttr_sets_with_action_delete(),
        window_ids=["w1", "w2"], active_window="w1",
        assignments=[0, 0], registry_mapping={"w1": "ttr", "w2": "ttr"},
        queue_obj=q,
    )
    _start_and_drain(svc, q, HOLD_SECONDS,
                     ("keydown", "space"), ("keyup", "space"))
    keydowns, keyups = _measure_hold(sent, "space", "w2")
    assert len(keydowns) == 1
    assert len(keyups) == 1
    measured = keyups[0][0] - keydowns[0][0]
    assert measured >= HOLD_SECONDS - TOLERANCE


def test_holding_movement_w_mirrors_duration_on_bg_toon(monkeypatch):
    """Movement key (forward = w) hold-duration mirroring."""
    q = queue.Queue()
    svc, sent = _make_svc(
        monkeypatch, _ttr_sets_with_action_delete(),
        window_ids=["w1", "w2"], active_window="w1",
        assignments=[0, 0], registry_mapping={"w1": "ttr", "w2": "ttr"},
        queue_obj=q,
    )
    _start_and_drain(svc, q, HOLD_SECONDS,
                     ("keydown", "w"), ("keyup", "w"))
    keydowns, keyups = _measure_hold(sent, "w", "w2")
    assert len(keydowns) == 1
    assert len(keyups) == 1
    measured = keyups[0][0] - keydowns[0][0]
    assert measured >= HOLD_SECONDS - TOLERANCE


def test_holding_f_key_mirrors_duration_on_bg_toon(monkeypatch):
    """F-key (catch-all ACTION path, not keymap-bound) hold mirroring."""
    q = queue.Queue()
    svc, sent = _make_svc(
        monkeypatch, _ttr_sets_with_action_delete(),
        window_ids=["w1", "w2"], active_window="w1",
        assignments=[0, 0], registry_mapping={"w1": "ttr", "w2": "ttr"},
        queue_obj=q,
    )
    _start_and_drain(svc, q, HOLD_SECONDS,
                     ("keydown", "F5"), ("keyup", "F5"))
    keydowns, keyups = _measure_hold(sent, "F5", "w2")
    assert len(keydowns) == 1
    assert len(keyups) == 1
    measured = keyups[0][0] - keydowns[0][0]
    assert measured >= HOLD_SECONDS - TOLERANCE


def test_holding_modifier_ctrl_mirrors_duration_on_bg_toon(monkeypatch):
    """Modifier (Control_L) hold mirroring via _send_modifier_to_bg."""
    q = queue.Queue()
    svc, sent = _make_svc(
        monkeypatch, _ttr_sets_with_action_delete(),
        window_ids=["w1", "w2"], active_window="w1",
        assignments=[0, 0], registry_mapping={"w1": "ttr", "w2": "ttr"},
        queue_obj=q,
    )
    _start_and_drain(svc, q, HOLD_SECONDS,
                     ("keydown", "Control_L"), ("keyup", "Control_L"))
    keydowns, keyups = _measure_hold(sent, "Control_L", "w2")
    assert len(keydowns) == 1
    assert len(keyups) == 1
    measured = keyups[0][0] - keydowns[0][0]
    assert measured >= HOLD_SECONDS - TOLERANCE


def test_hold_mirrors_on_all_bg_toons_with_four_toon_config(monkeypatch):
    """Four TTR toons; foreground = toon 1, bg = toons 2/3/4. All three
    bg toons receive a matched keydown/keyup pair."""
    q = queue.Queue()
    svc, sent = _make_svc(
        monkeypatch, _ttr_sets_with_action_delete(),
        window_ids=["w1", "w2", "w3", "w4"], active_window="w1",
        assignments=[0, 0, 0, 0],
        registry_mapping={"w1": "ttr", "w2": "ttr", "w3": "ttr", "w4": "ttr"},
        queue_obj=q,
    )
    _start_and_drain(svc, q, HOLD_SECONDS,
                     ("keydown", "Delete"), ("keyup", "Delete"))
    for win in ("w2", "w3", "w4"):
        keydowns, keyups = _measure_hold(sent, "Delete", win)
        assert len(keydowns) == 1, f"win {win} got {len(keydowns)} keydowns"
        assert len(keyups) == 1, f"win {win} got {len(keyups)} keyups"
        measured = keyups[0][0] - keydowns[0][0]
        assert measured >= HOLD_SECONDS - TOLERANCE


def test_hold_drains_immediately_on_focus_loss(monkeypatch):
    """Hold Delete, then simulate active-window change. Drain emits
    keyup BEFORE the user's keyup arrives."""
    q = queue.Queue()
    svc, sent = _make_svc(
        monkeypatch, _ttr_sets_with_action_delete(),
        window_ids=["w1", "w2"], active_window="w1",
        assignments=[0, 0], registry_mapping={"w1": "ttr", "w2": "ttr"},
        queue_obj=q,
    )

    q.put(("keydown", "Delete"))
    svc.start()
    try:
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline and not svc.holds.contains("Delete"):
            time.sleep(0.005)
        assert svc.holds.contains("Delete"), "precondition: keydown should have registered"

        svc.window_manager._active = "999999"
        time.sleep(0.1)
    finally:
        svc.stop(wait=True)

    keyups = [(t, a, w, k) for (t, a, w, k) in sent if a == "keyup" and k == "Delete" and w == "w2"]
    assert len(keyups) >= 1, (
        f"expected at least one Delete keyup to bg toon on focus loss, got: {keyups}"
    )
    assert not svc.holds.contains("Delete"), "registry should be drained after focus loss"


def test_hold_keyup_emitted_after_phantom_chat_activation(monkeypatch):
    """User holds Delete, then triggers phantom chat. On release, Delete
    keyup must still be emitted to bg toons."""
    q = queue.Queue()
    svc, sent = _make_svc(
        monkeypatch, _ttr_sets_with_action_delete(),
        window_ids=["w1", "w2"], active_window="w1",
        assignments=[0, 0], registry_mapping={"w1": "ttr", "w2": "ttr"},
        queue_obj=q,
    )
    monkeypatch.setattr(svc, "_phantom_gate_open", lambda: True)
    monkeypatch.setattr(svc, "get_chat_enabled", lambda: [True, True])

    svc.start()
    try:
        q.put(("keydown", "Delete"))
        time.sleep(0.05)
        for ch in ("a", "b", "c"):
            q.put(("keydown", ch))
            q.put(("keyup", ch))
            time.sleep(0.01)
        time.sleep(0.05)
        q.put(("keyup", "Delete"))
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline and not q.empty():
            time.sleep(0.005)
        time.sleep(0.08)
    finally:
        svc.stop(wait=True)

    keyups = [(t, a, w, k) for (t, a, w, k) in sent if a == "keyup" and k == "Delete" and w == "w2"]
    assert len(keyups) == 1, (
        f"expected exactly one Delete keyup to bg toon after phantom + release, got: {keyups}"
    )
