"""TTR per-toon routing tests.

The TTR else-branch in _send_logical_action_km uses strict per-toon
routing: each toon responds only to keys that its own assigned set
binds. No cross-game broadcast fallback.

Critically, the OUTBOUND key is always the game's default (set 0)
binding for the resolved action -- NOT the toon's assigned set's
binding. The set is an input-translation layer; the bg toon's
settings.json is the user's customized default, so the bg toon must
receive its native binding for the action.
"""

from unittest.mock import MagicMock

import pytest

from services.input_service import InputService
from utils import logical_actions


class _FakeKeymap:
    """Game -> list of sets (dict action->key). Index 0 is the default."""
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


# Sets used in these tests. Set 0 is "default" (WASD here, simulating
# the user's customization that defines the native binding). Set 1 is
# arrows. The keymap for TTR mirrors this structure.
_KM = {
    "ttr": [
        {"forward": "w",  "reverse": "s",    "left": "a",    "right": "d"},
        {"forward": "Up", "reverse": "Down", "left": "Left", "right": "Right"},
    ],
    "cc": [
        {"forward": "w",  "reverse": "s",    "left": "a",    "right": "d"},
        {"forward": "Up", "reverse": "Down", "left": "Left", "right": "Right"},
    ],
}


def _build_svc(monkeypatch, registry_mapping, focus_window_id, assignments):
    wm = _FakeWindowManager(list(registry_mapping.keys()), focus_window_id)
    fake_registry = _FakeRegistry(registry_mapping)
    monkeypatch.setattr(
        "utils.game_registry.GameRegistry.instance", lambda: fake_registry
    )
    sent = []
    svc = InputService(
        window_manager=wm,
        get_enabled_toons=lambda: [True] * len(registry_mapping),
        get_movement_modes=lambda: ["both"] * len(registry_mapping),
        get_event_queue_func=lambda: None,
        settings_manager=MagicMock(),
        get_keymap_assignments=lambda: list(assignments),
        keymap_manager=_FakeKeymap(_KM),
    )
    svc._send_via_backend = lambda action, win, keysym, mods=None: sent.append(
        (action, win, keysym)
    )
    svc._resolve_keysym = lambda k: k
    return svc, sent


class TestTtrPerToonRouting:
    def test_cc_focused_arrow_press_routes_ttr_arrows_bg_with_default_outbound(self, monkeypatch):
        """The user's reported bug: CC1 default focused, TTR2 arrows bg.
        Press Up. TTR2's set binds Up to forward; outbound must be the
        TTR DEFAULT's forward (W) -- not TTR2's set's forward (Up),
        because TTR2's settings.json is the user's WASD customization."""
        svc, sent = _build_svc(
            monkeypatch,
            registry_mapping={"100": "cc", "200": "ttr"},
            focus_window_id="100",
            assignments=[0, 1],  # CC1 default WASD, TTR2 arrows
        )
        svc._send_logical_action_km("keydown", "Up", [True, True], [0, 1])
        assert ("keydown", "200", "w") in sent

    def test_ttr_focused_default_press_routes_arrows_ttr_bg_via_legacy_fallback(self, monkeypatch):
        """TTR1 default WASD focused, TTR2 arrows bg. Press W. TTR2's
        arrows set doesn't bind W -- but foreground is TTR (same-game).
        Per the strict-same-game rule, this should NOT fall back to
        legacy. TTR2 is skipped."""
        svc, sent = _build_svc(
            monkeypatch,
            registry_mapping={"100": "ttr", "200": "ttr"},
            focus_window_id="100",
            assignments=[0, 1],  # TTR1 default, TTR2 arrows
        )
        svc._send_logical_action_km("keydown", "w", [True, True], [0, 1])
        sent_for_bg = [c for c in sent if c[1] == "200"]
        assert sent_for_bg == []

    def test_ttr_focused_default_press_routes_default_ttr_bg(self, monkeypatch):
        """Same-game broadcast still works for matching keys: TTR1
        default + TTR2 default, press W. Per-toon matches for TTR2;
        outbound is default's W."""
        svc, sent = _build_svc(
            monkeypatch,
            registry_mapping={"100": "ttr", "200": "ttr"},
            focus_window_id="100",
            assignments=[0, 0],
        )
        svc._send_logical_action_km("keydown", "w", [True, True], [0, 0])
        assert ("keydown", "200", "w") in sent

    def test_ttr_focused_arrow_press_routes_arrows_ttr_bg_via_per_toon(self, monkeypatch):
        """TTR1 default + TTR2 arrows, press Up. TTR1's set does not
        bind Up; TTR2's set does. Per-toon match for TTR2; outbound is
        default's forward (W) -- not arrows's Up."""
        svc, sent = _build_svc(
            monkeypatch,
            registry_mapping={"100": "ttr", "200": "ttr"},
            focus_window_id="100",
            assignments=[0, 1],
        )
        svc._send_logical_action_km("keydown", "Up", [True, True], [0, 1])
        assert ("keydown", "200", "w") in sent

    def test_cc_focused_wasd_press_does_not_route_to_ttr_arrows_bg(self, monkeypatch):
        """CC1 default + TTR2 arrows. Press W (in CC's default).
        TTR2's arrows set doesn't bind W. Strict per-toon: no fallback.
        TTR2 receives nothing."""
        svc, sent = _build_svc(
            monkeypatch,
            registry_mapping={"100": "cc", "200": "ttr"},
            focus_window_id="100",
            assignments=[0, 1],
        )
        svc._send_logical_action_km("keydown", "w", [True, True], [0, 1])
        assert ("keydown", "200", "w") not in sent
        sent_for_ttr2 = [c for c in sent if c[1] == "200"]
        assert sent_for_ttr2 == []

    def test_ttr_focused_skipped_when_focused(self, monkeypatch):
        """The focused TTR toon is never routed to (it gets native
        input). With per-toon match on the focused toon, the
        win==active_window guard still skips it."""
        svc, sent = _build_svc(
            monkeypatch,
            registry_mapping={"100": "ttr", "200": "ttr"},
            focus_window_id="100",
            assignments=[0, 0],
        )
        svc._send_logical_action_km("keydown", "w", [True, True], [0, 0])
        sent_for_focused = [c for c in sent if c[1] == "100"]
        assert sent_for_focused == []

    def test_outbound_always_uses_default_set_not_toons_set(self, monkeypatch):
        """Even when per-toon match succeeds (TTR2 on arrows binds Up),
        the outbound is the DEFAULT set's binding for the action
        (forward -> W), not the toon's set's binding (forward -> Up).
        This is the input-translation-layer semantic."""
        svc, sent = _build_svc(
            monkeypatch,
            registry_mapping={"100": "cc", "200": "ttr"},
            focus_window_id="100",
            assignments=[0, 1],  # TTR2 on arrows
        )
        svc._send_logical_action_km("keydown", "Up", [True, True], [0, 1])
        # If the fix is wrong and uses set_idx, this would send "Up".
        # The correct behavior is to send "w" (TTR's default forward).
        assert ("keydown", "200", "w") in sent
        assert ("keydown", "200", "Up") not in sent
