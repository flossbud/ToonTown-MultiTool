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


def test_ttr_routing_per_toon_strict_same_game(monkeypatch):
    """TTR1 (set 0, WASD) focused, TTR2 (set 1, arrows) background. Press W.
    Per-toon lookup: TTR2's arrows set does not bind W. Foreground is TTR
    (same-game) -> strict skip; no legacy fallback. TTR2 receives nothing.

    This verifies the strict-same-game rule: non-matching-set TTR toons are
    independent when the foreground toon is also TTR. The set is an
    input-translation layer; a bg toon that hasn't assigned that key does not
    move.

    Previously this test asserted the old buggy behavior: legacy_logical was
    used verbatim and outbound was emitted from set_idx (the toon's own set)
    rather than from the default (set 0). That was incorrect per the design
    clarification that the set is an input-translation layer only."""
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

    # TTR2's arrows set doesn't bind W; same-game strict rule skips it.
    svc._send_logical_action_km("keydown", "w", [True, True], [0, 1])
    assert sent == []


def test_global_chat_active_suppresses_all_routing(cc_setup):
    svc, sent = cc_setup
    svc.global_chat_active = True
    svc._send_logical_action_km("keydown", "w", [True, True], [1, 2])
    svc._send_logical_action_km("keydown", "Up", [True, True], [1, 2])
    assert sent == []


class TestHybridRoutingMixed:
    """The routing matrix from the spec, exercised against
    _send_logical_action_km. Each test sets up a 2-toon layout, simulates
    a single keydown, and asserts which toons receive bridge sends."""

    def _build_svc(self, monkeypatch, registry_mapping, focus_window_id, assignments):
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
            keymap_manager=_FakeKeymap({
                "ttr": [
                    {"forward": "Up", "reverse": "Down", "left": "Left", "right": "Right"},
                    {"forward": "w",  "reverse": "s",    "left": "a",    "right": "d"},
                ],
                "cc": [
                    {"forward": "w",  "reverse": "s",    "left": "a",    "right": "d"},
                    {"forward": "Up", "reverse": "Down", "left": "Left", "right": "Right"},
                ],
            }),
        )
        svc._send_via_backend = lambda action, win, keysym, mods=None: sent.append(
            (action, win, keysym)
        )
        svc._resolve_keysym = lambda k: k  # passthrough
        return svc, sent

    def test_ttr_focused_arrow_press_routes_cc_via_legacy_fallback(self, monkeypatch):
        """TTR1=arrows focused, CC2=WASD background, press Up.
        Hybrid: per-toon CC lookup on Up returns None; foreground is TTR
        (not CC) so fall back to legacy_logical=forward; CC2's set's
        forward is 'w'; send 'w' (canonical) to CC2."""
        svc, sent = self._build_svc(
            monkeypatch,
            registry_mapping={"100": "ttr", "200": "cc"},
            focus_window_id="100",
            assignments=[0, 0],  # TTR1 set 0 (arrows), CC2 set 0 (WASD)
        )
        svc._send_logical_action_km(
            "keydown", "Up", [True, True], [0, 0]
        )
        assert ("keydown", "200", "w") in sent

    def test_cc_focused_other_keyset_press_skips_cc_strict(self, monkeypatch):
        """CC1=WASD focused, CC2=arrows background, press W.
        Per-toon CC lookup on W binds 'forward' for CC1 (focused, skipped
        by key==canonical guard) and returns None for CC2 (arrows set
        doesn't bind W). Foreground IS CC -> no legacy fallback -> CC2
        is skipped. Only CC1 (focused, native) moves."""
        svc, sent = self._build_svc(
            monkeypatch,
            registry_mapping={"100": "cc", "200": "cc"},
            focus_window_id="100",
            assignments=[0, 1],  # CC1 WASD, CC2 arrows
        )
        svc._send_logical_action_km(
            "keydown", "w", [True, True], [0, 1]
        )
        sent_for_cc2 = [s for s in sent if s[1] == "200"]
        assert sent_for_cc2 == []

    def test_cc_focused_arrow_press_routes_cc_arrows_toon(self, monkeypatch):
        """CC1=WASD focused, CC2=arrows background, press Up.
        Per-toon CC lookup on Up returns None for CC1 (WASD set), returns
        'forward' for CC2 (arrows set, binds Up). CC2 gets canonical 'w'
        via bridge."""
        svc, sent = self._build_svc(
            monkeypatch,
            registry_mapping={"100": "cc", "200": "cc"},
            focus_window_id="100",
            assignments=[0, 1],
        )
        svc._send_logical_action_km(
            "keydown", "Up", [True, True], [0, 1]
        )
        assert ("keydown", "200", "w") in sent
        assert not any(s for s in sent if s[1] == "100")

    def test_ttr_focused_ttr_default_press_broadcasts_to_cc_only(self, monkeypatch):
        """TTR1=arrows focused, TTR2=WASD bg, CC3=WASD bg, press Up.
        TTR1 native (handled outside this function).
        TTR2: per-toon lookup -- TTR2's set 1 (WASD) doesn't bind Up.
        Foreground is TTR (same-game) -> strict skip; TTR2 receives nothing.
        CC3: per-toon Up->None on WASD set; foreground=TTR (cross-game for
        CC) -> legacy fallback: legacy_logical=forward -> canonical='w' ->
        send.

        Previously this test asserted TTR2 also received 'w', which was the
        old buggy behavior where legacy_logical was used verbatim for any
        background TTR toon regardless of its assigned set and foreground
        game. The strict-same-game rule now matches the CC branch's pattern:
        same-game bg toons are independent when their set doesn't bind the
        pressed key."""
        svc, sent = self._build_svc(
            monkeypatch,
            registry_mapping={"100": "ttr", "200": "ttr", "300": "cc"},
            focus_window_id="100",
            assignments=[0, 1, 0],  # TTR1 arrows, TTR2 WASD, CC3 WASD
        )
        svc._send_logical_action_km(
            "keydown", "Up", [True, True, True], [0, 1, 0]
        )
        assert ("keydown", "200", "w") not in sent  # TTR2 strict-skipped (same-game, mismatched set)
        assert ("keydown", "300", "w") in sent  # CC3 bridged via hybrid cross-game fallback

    def test_cc_focused_native_press_routes_ttr_bg_via_legacy(self, monkeypatch):
        """TTR1=arrows + CC2=WASD, focus CC2, press W (CC2's canonical).
        CC2 (focused) skipped by key==canonical guard.
        TTR1 (background): legacy_logical=forward (CC2's set's forward=w
        -> CC default-set forward=w). get_key_for_action(ttr, 0, forward)
        = 'Up'. Send Up to TTR1 via bridge."""
        svc, sent = self._build_svc(
            monkeypatch,
            registry_mapping={"100": "ttr", "200": "cc"},
            focus_window_id="200",
            assignments=[0, 0],  # TTR1 arrows (set 0), CC2 WASD (set 0)
        )
        svc._send_logical_action_km(
            "keydown", "w", [True, True], [0, 0]
        )
        assert ("keydown", "100", "Up") in sent
        # CC2 is focused and key == canonical -> not sent via bridge.
        assert not any(s for s in sent if s[1] == "200")

    def test_ttr_focused_arrow_press_routes_arrows_cc_via_per_toon(self, monkeypatch):
        """TTR1=arrows + CC2=arrows, TTR1 focused, press Up.
        Per-toon CC lookup for CC2: get_action_in_set('cc', arrows, Up)
        = 'forward' (binds Up). So the per-toon match path fires (NOT the
        hybrid fallback). canonical='w'. Send 'w' to CC2 via bridge."""
        svc, sent = self._build_svc(
            monkeypatch,
            registry_mapping={"100": "ttr", "200": "cc"},
            focus_window_id="100",
            assignments=[0, 1],  # TTR1 arrows (set 0), CC2 arrows (set 1)
        )
        svc._send_logical_action_km(
            "keydown", "Up", [True, True], [0, 1]
        )
        assert ("keydown", "200", "w") in sent
