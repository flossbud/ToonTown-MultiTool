"""Per-toon CC routing tests for _send_logical_action_km.

The function now has two paths:
- CC toons: per-toon set lookup; canonical key emitted to target window;
  foreground skipped only if pressed key already matches canonical.
- TTR toons: unchanged legacy broadcast-with-translation.
"""

from unittest.mock import MagicMock

import pytest

from services.input_service import InputService
from utils import logical_actions


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
        return frozenset({"w", "a", "s", "d", "Up", "Down", "Left", "Right", "space"})


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


@pytest.fixture
def cc_setup(monkeypatch):
    """Two CC toons. Toon 1 (w1) = WASD set; toon 2 (w2) = arrows set.
    Active = w1. CC Default = WASD."""
    keymap = _FakeKeymap({
        "cc": [
            {"forward": "w", "reverse": "s", "left": "a", "right": "d",
             "jump": "space", "gags": "q", "tasks": "e", "book": "Escape", "map": "Alt_L", "sprint": "Shift_L"},
            {"forward": "w", "reverse": "s", "left": "a", "right": "d",
             "jump": "space", "gags": "q", "tasks": "e", "book": "Escape", "map": "Alt_L", "sprint": "Shift_L"},
            {"forward": "Up", "reverse": "Down", "left": "Left", "right": "Right",
             "jump": "space", "gags": "q", "tasks": "e", "book": "Escape", "map": "Alt_L", "sprint": "Shift_L"},
        ],
        "ttr": [
            {"forward": "w", "reverse": "s", "left": "a", "right": "d",
             "jump": "space", "gags": "g", "tasks": "t", "book": "Alt_L", "map": "Shift_L"},
        ],
    })
    wm = _FakeWindowManager(window_ids=["w1", "w2"], active_window="w1")

    from utils import game_registry as gr
    fake_reg = _FakeRegistry({"w1": "cc", "w2": "cc"})
    monkeypatch.setattr(gr.GameRegistry, "instance", lambda: fake_reg)

    sent = []
    svc = InputService(
        window_manager=wm,
        get_enabled_toons=lambda: [True, True],
        get_movement_modes=lambda: ["both", "both"],
        get_event_queue_func=lambda: None,
        settings_manager=MagicMock(),
        get_keymap_assignments=lambda: [1, 2],
        keymap_manager=keymap,
    )
    monkeypatch.setattr(svc, "_send_via_backend", lambda action, win, keysym, modifiers=None: sent.append((action, win, keysym)))
    monkeypatch.setattr(svc, "_foreground_game", lambda: "cc")
    return svc, sent


def test_press_w_with_toon1_focused_skips_foreground_and_does_not_route_to_toon2(cc_setup):
    """User presses w. Toon 1 (focused, WASD set, canonical=w): skip (OS handles). Toon 2 (arrows set): w not bound → no route."""
    svc, sent = cc_setup
    svc._send_logical_action_km("keydown", "w", [True, True], [1, 2])
    assert sent == []


def test_press_up_with_toon1_focused_routes_to_toon2_with_canonical_w(cc_setup):
    """User presses Up. Toon 1 (focused, WASD set): Up not bound → no route. Toon 2 (arrows set, Up=forward): send canonical w."""
    svc, sent = cc_setup
    svc._send_logical_action_km("keydown", "Up", [True, True], [1, 2])
    assert sent == [("keydown", "w2", "w")]


def test_press_up_with_toon2_focused_routes_canonical_w_to_focused_toon2(cc_setup):
    """User presses Up on focused toon 2 (arrows set, Up=forward).
    Up != canonical w, so foreground is NOT skipped; bridge sends w to toon 2.
    Toon 1 (background, WASD set): Up not bound → no route."""
    svc, sent = cc_setup
    svc.window_manager._active = "w2"
    svc._send_logical_action_km("keydown", "Up", [True, True], [1, 2])
    assert sent == [("keydown", "w2", "w")]


def test_press_w_with_toon2_focused_routes_to_toon1(cc_setup):
    """Toon 2 focused (arrows set, w not bound) → no route. Toon 1 background (WASD, w=forward): canonical=w. Send w to toon 1."""
    svc, sent = cc_setup
    svc.window_manager._active = "w2"
    svc._send_logical_action_km("keydown", "w", [True, True], [1, 2])
    assert sent == [("keydown", "w1", "w")]


def test_both_toons_with_wasd_set_press_w_routes_only_to_background(cc_setup):
    """Two toons both using WASD set. Press w with toon 1 focused.
    Foreground (toon 1, w=canonical): skip. Background (toon 2): canonical=w → send w."""
    svc, sent = cc_setup
    svc.get_keymap_assignments = lambda: [1, 1]
    svc._send_logical_action_km("keydown", "w", [True, True], [1, 1])
    assert sent == [("keydown", "w2", "w")]


def test_non_movement_action_uses_cc_default_binding_as_canonical(cc_setup):
    """jump=space lives in both sets; CC Default's binding is the canonical for non-movement.
    Press space with toon 1 focused. Toon 2 (set 2) binds space=jump → canonical (CC Default jump) = space.
    Foreground: space == canonical → skip. Background: send space."""
    svc, sent = cc_setup
    svc._send_logical_action_km("keydown", "space", [True, True], [1, 2])
    assert sent == [("keydown", "w2", "space")]


def test_ttr_routing_unchanged(monkeypatch):
    """TTR toons keep legacy resolve-via-foreground-default + send toon-set[action] to bg."""
    keymap = _FakeKeymap({
        "cc": [
            {"forward": "w", "reverse": "s", "left": "a", "right": "d"},
        ],
        "ttr": [
            {"forward": "w", "reverse": "s", "left": "a", "right": "d", "jump": "space", "gags": "g", "tasks": "t", "book": "Alt_L", "map": "Shift_L"},
            {"forward": "Up", "reverse": "Down", "left": "Left", "right": "Right", "jump": "space", "gags": "g", "tasks": "t", "book": "Alt_L", "map": "Shift_L"},
        ],
    })
    wm = _FakeWindowManager(window_ids=["w1", "w2"], active_window="w1")
    from utils import game_registry as gr
    monkeypatch.setattr(gr.GameRegistry, "instance", lambda: _FakeRegistry({"w1": "ttr", "w2": "ttr"}))

    sent = []
    svc = InputService(
        window_manager=wm,
        get_enabled_toons=lambda: [True, True],
        get_movement_modes=lambda: ["both", "both"],
        get_event_queue_func=lambda: None,
        settings_manager=MagicMock(),
        get_keymap_assignments=lambda: [0, 1],
        keymap_manager=keymap,
    )
    monkeypatch.setattr(svc, "_send_via_backend", lambda action, win, keysym, modifiers=None: sent.append((action, win, keysym)))
    monkeypatch.setattr(svc, "_foreground_game", lambda: "ttr")

    # Legacy: press w on foreground → resolve via TTR Default (w=forward) → for bg toon 2 send set[forward]=Up.
    svc._send_logical_action_km("keydown", "w", [True, True], [0, 1])
    assert sent == [("keydown", "w2", "Up")]


def test_global_chat_active_suppresses_all_routing(cc_setup):
    svc, sent = cc_setup
    svc.global_chat_active = True
    svc._send_logical_action_km("keydown", "w", [True, True], [1, 2])
    svc._send_logical_action_km("keydown", "Up", [True, True], [1, 2])
    assert sent == []
