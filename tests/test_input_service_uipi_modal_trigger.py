import queue
from unittest.mock import MagicMock

import pytest

from services.input_service import InputService
from utils.win32_integrity import Capability


class _Clock:
    def __init__(self): self.t = 0.0
    def __call__(self): return self.t


def _svc(cap_by_win, clock, active="w1", enabled=(True, True), ids=("w1", "w2")):
    wm = MagicMock()
    wm.get_active_window.return_value = active
    wm.get_window_ids.return_value = list(ids)
    s = InputService(
        window_manager=wm,
        get_enabled_toons=lambda: list(enabled),
        get_movement_modes=lambda: ["both", "both"],
        get_event_queue_func=lambda: queue.Queue(),
        settings_manager=MagicMock(),
        get_keymap_assignments=lambda: [0, 0],
        keymap_manager=MagicMock(),
        capability_provider=lambda hwnd: cap_by_win.get(str(hwnd), Capability.OK),
    )
    s._uipi_clock = clock
    return s


def _collect(s):
    fired = []
    s.uipi_blocked_movement_detected.connect(lambda d: fired.append(d))
    return fired


def test_two_blocked_keydowns_within_5s_fires_once():
    c = _Clock(); s = _svc({"w2": Capability.BLOCKED_UIPI}, c); fired = _collect(s)
    s._note_blocked_movement("w2", "forward", "w"); s._release_uipi_hold("w")
    c.t = 2.0
    s._note_blocked_movement("w2", "forward", "w"); s._release_uipi_hold("w")
    assert len(fired) == 1


def test_single_tap_does_not_fire():
    c = _Clock(); s = _svc({"w2": Capability.BLOCKED_UIPI}, c); fired = _collect(s)
    s._note_blocked_movement("w2", "forward", "w"); s._release_uipi_hold("w")
    assert fired == []


def test_held_750ms_fires_on_release():
    c = _Clock(); s = _svc({"w2": Capability.BLOCKED_UIPI}, c); fired = _collect(s)
    s._note_blocked_movement("w2", "forward", "w")     # down, held
    c.t = 0.8
    assert fired == []                                  # not while held
    s._release_uipi_hold("w")
    assert len(fired) == 1


def test_latched_fires_only_once():
    c = _Clock(); s = _svc({"w2": Capability.BLOCKED_UIPI}, c); fired = _collect(s)
    for t in (0.0, 2.0, 4.0, 6.0):
        c.t = t
        s._note_blocked_movement("w2", "forward", "w"); s._release_uipi_hold("w")
    assert len(fired) == 1


def test_reset_latch_rearms():
    c = _Clock(); s = _svc({"w2": Capability.BLOCKED_UIPI}, c); fired = _collect(s)
    s._note_blocked_movement("w2", "forward", "w"); s._release_uipi_hold("w")
    c.t = 1.0
    s._note_blocked_movement("w2", "forward", "w"); s._release_uipi_hold("w")
    assert len(fired) == 1
    s.reset_uipi_latch()
    c.t = 10.0
    s._note_blocked_movement("w2", "forward", "w"); s._release_uipi_hold("w")
    c.t = 11.0
    s._note_blocked_movement("w2", "forward", "w"); s._release_uipi_hold("w")
    assert len(fired) == 2


def test_ok_target_never_fires():
    c = _Clock(); s = _svc({"w2": Capability.OK}, c); fired = _collect(s)
    s._note_blocked_movement("w2", "forward", "w"); s._release_uipi_hold("w")
    c.t = 2.0
    s._note_blocked_movement("w2", "forward", "w"); s._release_uipi_hold("w")
    assert fired == []


def test_unknown_target_never_fires():
    c = _Clock(); s = _svc({"w2": Capability.UNKNOWN}, c); fired = _collect(s)
    s._note_blocked_movement("w2", "forward", "w"); s._release_uipi_hold("w")
    c.t = 2.0
    s._note_blocked_movement("w2", "forward", "w"); s._release_uipi_hold("w")
    assert fired == []


def test_non_movement_action_ignored():
    c = _Clock(); s = _svc({"w2": Capability.BLOCKED_UIPI}, c); fired = _collect(s)
    s._note_blocked_movement("w2", "jump", "space"); s._release_uipi_hold("space")
    c.t = 2.0
    s._note_blocked_movement("w2", "jump", "space"); s._release_uipi_hold("space")
    assert fired == []


def test_foreground_target_ignored():
    # win == active window -> not a background target.
    c = _Clock(); s = _svc({"w1": Capability.BLOCKED_UIPI}, c, active="w1"); fired = _collect(s)
    s._note_blocked_movement("w1", "forward", "w"); s._release_uipi_hold("w")
    c.t = 2.0
    s._note_blocked_movement("w1", "forward", "w"); s._release_uipi_hold("w")
    assert fired == []


def test_ttmt_window_focus_ignored():
    # active window is the TTMT window (not in managed game ids) -> ignore.
    c = _Clock(); s = _svc({"w2": Capability.BLOCKED_UIPI}, c, active="ttmt"); fired = _collect(s)
    s._note_blocked_movement("w2", "forward", "w"); s._release_uipi_hold("w")
    c.t = 2.0
    s._note_blocked_movement("w2", "forward", "w"); s._release_uipi_hold("w")
    assert fired == []


@pytest.mark.parametrize("flag", ["global_chat_active", "_phantom_active", "_strict_drain_active"])
def test_capture_state_ignored(flag):
    c = _Clock(); s = _svc({"w2": Capability.BLOCKED_UIPI}, c); fired = _collect(s)
    setattr(s, flag, True)
    s._note_blocked_movement("w2", "forward", "w"); s._release_uipi_hold("w")
    c.t = 2.0
    s._note_blocked_movement("w2", "forward", "w"); s._release_uipi_hold("w")
    assert fired == []


def test_autorepeat_keydown_is_not_a_second_episode():
    # A second keydown for a still-held key is autorepeat: it must NOT count as a
    # new episode (otherwise one physical press would satisfy the 2-in-5s rule).
    # Release before the 750ms hold threshold so the hold rule does not fire
    # either -> a single short press with autorepeat triggers nothing.
    c = _Clock(); s = _svc({"w2": Capability.BLOCKED_UIPI}, c); fired = _collect(s)
    s._note_blocked_movement("w2", "forward", "w")   # episode 1, down @ t=0
    c.t = 0.1
    s._note_blocked_movement("w2", "forward", "w")   # still held -> autorepeat, not episode 2
    s._release_uipi_hold("w")                        # held 0.1s < 0.75 -> no hold-rule fire
    assert fired == []


def test_autorepeat_preserves_original_hold_timestamp_so_real_hold_fires():
    # The autorepeat guard must NOT reset the press timestamp: a genuinely held
    # key (real keydown at t=0, an autorepeat re-report, then release past 750ms)
    # still fires the hold rule measured from the ORIGINAL press.
    c = _Clock(); s = _svc({"w2": Capability.BLOCKED_UIPI}, c); fired = _collect(s)
    s._note_blocked_movement("w2", "forward", "w")   # down @ t=0
    c.t = 0.5
    s._note_blocked_movement("w2", "forward", "w")   # autorepeat (ignored, timestamp untouched)
    c.t = 0.9
    s._release_uipi_hold("w")                        # 0.9s from the original press >= 0.75 -> fire
    assert len(fired) == 1


def test_details_aggregates_all_blocked_bg_targets():
    c = _Clock()
    s = _svc({"w2": Capability.BLOCKED_UIPI, "w3": Capability.BLOCKED_UIPI}, c,
             enabled=(True, True, True), ids=("w1", "w2", "w3"))
    fired = _collect(s)
    s._note_blocked_movement("w2", "forward", "w"); s._release_uipi_hold("w")
    c.t = 2.0
    s._note_blocked_movement("w2", "forward", "w"); s._release_uipi_hold("w")
    assert len(fired) == 1
    wins = {t["window_id"] for t in fired[0]["targets"]}
    assert wins == {"w2", "w3"}


def test_router_notes_blocked_bg_movement(monkeypatch):
    # Drives the REAL router _send_logical_action_km for a background BLOCKED
    # target, twice within 5s; the signal must fire once with that target.
    c = _Clock()
    s = _svc({"w2": Capability.BLOCKED_UIPI}, c)
    km = MagicMock()
    km.get_action_in_set.side_effect = lambda game, idx, key: "forward" if key == "w" else None
    km.get_key_for_action.return_value = "w"
    s.keymap_manager = km
    s._resolve_keysym = lambda k: k
    s._send_via_backend = lambda *a, **k: None
    from utils import game_registry as gr, logical_actions
    reg = MagicMock(); reg.get_game_for_window.return_value = "ttr"
    monkeypatch.setattr(gr.GameRegistry, "instance", lambda: reg)
    monkeypatch.setattr(logical_actions, "supports", lambda g, a: True)
    fired = []
    s.uipi_blocked_movement_detected.connect(lambda d: fired.append(d))
    s._send_logical_action_km("keydown", "w", [True, True], [0, 0]); s._release_uipi_hold("w")
    c.t = 1.0
    s._send_logical_action_km("keydown", "w", [True, True], [0, 0]); s._release_uipi_hold("w")
    assert len(fired) == 1
    assert fired[0]["window_id"] == "w2"


def test_router_foreground_target_not_recorded(monkeypatch):
    # A movement route to the FOREGROUND target (win == active) must not record.
    c = _Clock()
    s = _svc({"w1": Capability.BLOCKED_UIPI}, c, active="w1")
    km = MagicMock()
    km.get_action_in_set.side_effect = lambda game, idx, key: "forward" if key == "w" else None
    km.get_key_for_action.return_value = "w"
    s.keymap_manager = km
    s._resolve_keysym = lambda k: k
    s._send_via_backend = lambda *a, **k: None
    from utils import game_registry as gr, logical_actions
    reg = MagicMock(); reg.get_game_for_window.return_value = "ttr"
    monkeypatch.setattr(gr.GameRegistry, "instance", lambda: reg)
    monkeypatch.setattr(logical_actions, "supports", lambda g, a: True)
    # strict not active in this unit harness, so the active/fg target is skipped by the
    # existing `win == active_window and not strict` continue; even if it sent, the fg
    # guard in _note_blocked_movement excludes win==active. Assert no fire either way.
    fired = []
    s.uipi_blocked_movement_detected.connect(lambda d: fired.append(d))
    s._send_logical_action_km("keydown", "w", [True, True], [0, 0]); s._release_uipi_hold("w")
    c.t = 1.0
    s._send_logical_action_km("keydown", "w", [True, True], [0, 0]); s._release_uipi_hold("w")
    assert fired == []


def test_production_cache_path_requires_refresh_for_background_modal():
    # Regression for the final-review D1 bug: with the REAL WindowCapabilityCache,
    # a never-refreshed BACKGROUND window peeks UNKNOWN, so the modal does NOT fire
    # (the feature's primary case was broken). After _refresh_uipi_capabilities
    # populates all managed windows off the hot path, peek returns BLOCKED_UIPI and
    # the modal fires.
    from utils.win32_integrity import WindowCapabilityCache
    c = _Clock()
    s = _svc({}, c, active="1", ids=("1", "2"))
    cache = WindowCapabilityCache(
        reader=lambda h: Capability.BLOCKED_UIPI if h == 2 else Capability.OK,
        pid_of=lambda h: 1, ttl=3.0, clock=c)
    s._capability_cache = cache
    s._capability_provider = lambda w: cache.peek(int(w))   # hot path = peek only
    fired = _collect(s)

    # Background "2" never refreshed -> peek UNKNOWN -> no episode (the bug).
    s._note_blocked_movement("2", "forward", "w"); s._release_uipi_hold("w")
    c.t = 1.0
    s._note_blocked_movement("2", "forward", "w"); s._release_uipi_hold("w")
    assert fired == []

    # Off-hot-path refresh of ALL managed windows (focus/assignment/timer).
    s._refresh_uipi_capabilities()
    c.t = 2.0
    s._note_blocked_movement("2", "forward", "w"); s._release_uipi_hold("w")
    c.t = 3.0
    s._note_blocked_movement("2", "forward", "w"); s._release_uipi_hold("w")
    assert len(fired) == 1
    assert fired[0]["window_id"] == "2"


def test_refresh_uipi_capabilities_refreshes_every_managed_window():
    from utils.win32_integrity import WindowCapabilityCache
    c = _Clock()
    s = _svc({}, c, ids=("1", "2", "3"))
    got = []
    s._capability_cache = WindowCapabilityCache(
        reader=lambda h: got.append(h) or Capability.OK,
        pid_of=lambda h: 1, ttl=3.0, clock=c)
    s._refresh_uipi_capabilities()
    assert sorted(got) == [1, 2, 3]


def test_refresh_uipi_capabilities_noop_without_cache():
    c = _Clock()
    s = _svc({}, c)
    s._capability_cache = None
    s._refresh_uipi_capabilities()   # must not raise
