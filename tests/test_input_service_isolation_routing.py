"""Tests for the isolation-aware routing branch in InputService."""

from unittest.mock import MagicMock

import pytest

from services.input_service import InputService
from utils import logical_actions, settings_keys


class _FakeKeymap:
    def __init__(self, sets):
        """sets is a dict: game -> list of {action: key} dicts."""
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
def cc_only_setup(monkeypatch):
    """Two CC toons. Toon 1 (window 'w1') uses WASD set, toon 2 (window 'w2') uses arrows set.
    Active window is 'w1'."""
    keymap = _FakeKeymap({
        "cc": [
            # set 0: CC Default (matches what TTMT's CC default reflects)
            {"forward": "w", "reverse": "s", "left": "a", "right": "d"},
            # set 1: WASD
            {"forward": "w", "reverse": "s", "left": "a", "right": "d"},
            # set 2: arrows
            {"forward": "Up", "reverse": "Down", "left": "Left", "right": "Right"},
        ],
        "ttr": [
            {"forward": "w", "reverse": "s", "left": "a", "right": "d"},
        ],
    })
    wm = _FakeWindowManager(window_ids=["w1", "w2"], active_window="w1")

    from utils import game_registry as gr
    fake_reg = _FakeRegistry({"w1": "cc", "w2": "cc"})
    monkeypatch.setattr(gr.GameRegistry, "instance", lambda: fake_reg)

    settings = MagicMock()
    settings.get.side_effect = lambda key, default=None: {
        settings_keys.ISOLATION_ENABLED: True,
        settings_keys.ISOLATION_CANONICAL: "wasd",
    }.get(key, default)

    sent = []

    svc = InputService(
        window_manager=wm,
        get_enabled_toons=lambda: [True, True],
        get_movement_modes=lambda: ["both", "both"],
        get_event_queue_func=lambda: None,
        settings_manager=settings,
        get_keymap_assignments=lambda: [1, 2],  # toon 1=WASD set, toon 2=arrows set
        keymap_manager=keymap,
    )

    def fake_send(action, win_id, keysym, modifiers=None):
        sent.append((action, win_id, keysym))
    monkeypatch.setattr(svc, "_send_via_backend", fake_send)
    monkeypatch.setattr(svc, "_foreground_game", lambda: "cc")

    return svc, sent


def test_isolation_off_uses_legacy_per_toon_keyset_routing(cc_only_setup, monkeypatch):
    """Regression guard: when ISOLATION_ENABLED=False, behavior matches today's code."""
    svc, sent = cc_only_setup
    svc.settings_manager.get.side_effect = lambda key, default=None: {
        settings_keys.ISOLATION_ENABLED: False,
    }.get(key, default)

    svc._send_logical_action_km("keydown", "w", [True, True], [1, 2])

    # Today: w resolves via foreground default ("w"=forward), toon 2's arrows
    # set forward=Up, so toon 2 receives Up.
    assert sent == [("keydown", "w2", "Up")]


def test_isolation_on_emits_canonical_for_background_cc_toon(cc_only_setup):
    """ISOLATION on, canonical=WASD: toon 2 (arrows set) binds Up=forward; receives 'w' (canonical wasd), not 'Up' (its set's raw key)."""
    svc, sent = cc_only_setup
    # Press Up -- toon 2's arrows set binds Up=forward; canonical=wasd means outbound='w'.
    svc._send_logical_action_km("keydown", "Up", [True, True], [1, 2])

    assert sent == [("keydown", "w2", "w")]


def test_isolation_on_resolves_action_via_pressed_toon_set(cc_only_setup):
    """Wedge fix: press Up while toon 1 (WASD set) focused. Toon 2's arrows set
    binds Up=forward, so toon 2 gets canonical 'w'. Toon 1 gets nothing."""
    svc, sent = cc_only_setup
    svc._send_logical_action_km("keydown", "Up", [True, True], [1, 2])

    assert sent == [("keydown", "w2", "w")]


def test_isolation_on_action_collision_broadcasts_to_both(cc_only_setup):
    """If two toons bind the same physical key to forward, both receive canonical."""
    svc, sent = cc_only_setup
    # Both sets bind 'w' -> forward (set 1 = WASD, override set 2 in get_keymap_assignments).
    svc.get_keymap_assignments = lambda: [1, 1]
    svc.window_manager._active = None  # neither window is active

    svc._send_logical_action_km("keydown", "w", [True, True], [1, 1])

    assert ("keydown", "w1", "w") in sent
    assert ("keydown", "w2", "w") in sent


def test_isolation_does_not_affect_ttr_routing(cc_only_setup, monkeypatch):
    """TTR toons keep legacy routing even when isolation is on."""
    svc, sent = cc_only_setup

    from utils import game_registry as gr
    fake_reg = _FakeRegistry({"w1": "ttr", "w2": "ttr"})
    monkeypatch.setattr(gr.GameRegistry, "instance", lambda: fake_reg)
    monkeypatch.setattr(svc, "_foreground_game", lambda: "ttr")

    svc._send_logical_action_km("keydown", "w", [True, True], [0, 0])

    # TTR set 0 has forward=w, so toon 2 receives w (background). Active is w1.
    assert sent == [("keydown", "w2", "w")]


def test_isolation_on_arrows_canonical_emits_arrow_up(cc_only_setup):
    """canonical=arrows: toon 2 (arrows set) binds Up=forward; pressing Up sends Up (canonical arrows), not 'w'."""
    svc, sent = cc_only_setup
    svc.settings_manager.get.side_effect = lambda key, default=None: {
        settings_keys.ISOLATION_ENABLED: True,
        settings_keys.ISOLATION_CANONICAL: "arrows",
    }.get(key, default)

    # Press Up -- toon 2's arrows set binds Up=forward; canonical=arrows means outbound='Up'.
    svc._send_logical_action_km("keydown", "Up", [True, True], [1, 2])

    assert sent == [("keydown", "w2", "Up")]
