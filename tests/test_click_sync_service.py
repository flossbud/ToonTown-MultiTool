"""ClickSyncService orchestration tests with injected fakes."""
import pytest

from services.click_sync_service import ClickSyncService, MOTION_COALESCE_S


class FakeBackend:
    def __init__(self):
        self.calls = []  # (kind, wid, x, y, root_x, root_y, state, time)

    def send_button_press(self, wid, x, y, root_x, root_y, button=1, state=0, time=0):
        self.calls.append(("press", wid, x, y, root_x, root_y, state, time))
        return True

    def send_button_release(self, wid, x, y, root_x, root_y, button=1, state=0, time=0):
        self.calls.append(("release", wid, x, y, root_x, root_y, state, time))
        return True

    def send_motion(self, wid, x, y, root_x, root_y, state=0, time=0):
        self.calls.append(("motion", wid, x, y, root_x, root_y, state, time))
        return True


class FakeCapture:
    def __init__(self, on_event):
        self.on_event = on_event
        self.started = False

    def start(self):
        self.started = True
        return True

    def stop(self):
        self.started = False

    def is_running(self):
        return self.started


@pytest.fixture
def svc():
    geoms = {
        "10": (0, 0, 1000, 500),
        "20": (1100, 0, 1000, 500),
        "30": (0, 600, 2000, 1000),   # same aspect, double size
    }
    backend = FakeBackend()
    captures = []

    def capture_factory(on_event):
        c = FakeCapture(on_event)
        captures.append(c)
        return c

    s = ClickSyncService(
        slot_window_resolver=lambda slot: {0: "10", 1: "20", 2: "30"}.get(slot),
        geometry_provider=lambda wid: geoms.get(wid),
        source_resolver=lambda rx, ry, wids: next(
            (w for w in wids
             if geoms.get(w)
             and geoms[w][0] <= rx < geoms[w][0] + geoms[w][2]
             and geoms[w][1] <= ry < geoms[w][1] + geoms[w][3]), None),
        backend=backend,
        capture_factory=capture_factory,
    )
    s.set_enabled(True)
    yield s, backend, captures
    s.shutdown()


def _press(s, x, y, t=1000):
    s._on_capture_event("press", x, y, 0, t)


def _release(s, x, y, t=1100):
    s._on_capture_event("release", x, y, 256, t)


def test_capture_starts_only_when_group_active(svc):
    s, backend, captures = svc
    assert not captures or not captures[-1].started
    s.toggle_slot(0)
    assert s.slot_states()[0] == "armed"
    s.toggle_slot(1)
    assert s.slot_states()[0] == "active"
    assert captures[-1].started


def test_press_forwards_to_other_members_scaled(svc):
    s, backend, _ = svc
    s.toggle_slot(0)
    s.toggle_slot(2)  # window "30": double size, same aspect
    _press(s, 500, 250)  # center of "10"
    presses = [c for c in backend.calls if c[0] == "press"]
    assert len(presses) == 1
    kind, wid, x, y, rx, ry, state, t = presses[0]
    assert wid == "30"
    assert (x, y) == (1000, 500)        # center of the double-size target
    assert (rx, ry) == (0 + 1000, 600 + 500)  # target origin + mapped point
    assert t == 1000                     # captured timestamp forwarded


def test_release_goes_to_press_targets_with_state(svc):
    s, backend, _ = svc
    s.toggle_slot(0); s.toggle_slot(1)
    _press(s, 500, 250)
    _release(s, 600, 250)
    releases = [c for c in backend.calls if c[0] == "release"]
    assert len(releases) == 1
    assert releases[0][1] == "20"
    assert releases[0][6] == 256  # captured state passes through


def test_release_outside_source_not_clamped(svc):
    s, backend, _ = svc
    s.toggle_slot(0); s.toggle_slot(1)
    _press(s, 500, 250)
    _release(s, -50, 250)  # left of window "10"
    rel = [c for c in backend.calls if c[0] == "release"][0]
    assert rel[2] < 0  # out-of-bounds passes through


def test_click_outside_members_ignored(svc):
    s, backend, _ = svc
    s.toggle_slot(0); s.toggle_slot(1)
    _press(s, 5000, 5000)
    assert backend.calls == []


def test_motion_coalesced_and_flushed_before_release(svc, monkeypatch):
    s, backend, _ = svc
    s.toggle_slot(0); s.toggle_slot(1)
    clock = {"t": 100.0}
    monkeypatch.setattr("services.click_sync_service.monotonic",
                        lambda: clock["t"])
    _press(s, 100, 100)
    s._on_capture_event("motion", 110, 100, 256, 1001)  # first: emitted
    s._on_capture_event("motion", 120, 100, 256, 1002)  # within window: pending
    s._on_capture_event("motion", 130, 100, 256, 1003)  # replaces pending
    motions = [c for c in backend.calls if c[0] == "motion"]
    assert len(motions) == 1
    _release(s, 140, 100)
    motions = [c for c in backend.calls if c[0] == "motion"]
    assert len(motions) == 2            # pending (130,100) flushed pre-release
    assert backend.calls[-1][0] == "release"


def test_motion_without_gesture_outside_members_ignored(svc):
    s, backend, _ = svc
    s.toggle_slot(0); s.toggle_slot(1)
    s._on_capture_event("motion", 5000, 5000, 0, 1001)
    assert backend.calls == []


def test_drain_on_member_toggle_off_midgesture(svc):
    s, backend, _ = svc
    s.toggle_slot(0); s.toggle_slot(1)
    _press(s, 500, 250)
    s.toggle_slot(1)  # leave the group mid-press
    releases = [c for c in backend.calls if c[0] == "release"]
    assert len(releases) == 1
    assert releases[0][6] & 256          # Button1Mask set on the drain release
    assert releases[0][7] == 1000        # press timestamp reused
    # The later physical release is ignored (gesture consumed).
    _release(s, 600, 250)
    assert len([c for c in backend.calls if c[0] == "release"]) == 1


def test_drain_on_disable_and_shutdown_idempotent(svc):
    s, backend, _ = svc
    s.toggle_slot(0); s.toggle_slot(1)
    _press(s, 500, 250)
    s.set_enabled(False)
    assert [c for c in backend.calls if c[0] == "release"]
    s.shutdown()
    s.shutdown()  # idempotent


def test_disable_retains_membership(svc):
    s, backend, _ = svc
    s.toggle_slot(0); s.toggle_slot(1)
    s.set_enabled(False)
    assert s.slot_states() == {0: "off", 1: "off", 2: "off", 3: "off"}
    s.set_enabled(True)
    assert s.slot_states()[0] == "active" and s.slot_states()[1] == "active"


def test_mismatch_pauses_group(svc):
    s, backend, _ = svc
    geoms_bad = {"10": (0, 0, 1000, 500), "20": (1100, 0, 1000, 800)}
    s._geometry_provider = lambda wid: geoms_bad.get(wid)
    s.toggle_slot(0); s.toggle_slot(1)
    states = s.slot_states()
    assert states[0] == "error" and states[1] == "error"
    _press(s, 500, 250)
    assert backend.calls == []  # paused: nothing forwarded


def test_missing_window_slot_error_others_armed(svc):
    s, backend, _ = svc
    s.toggle_slot(0); s.toggle_slot(1); s.toggle_slot(3)  # slot 3 has no window
    states = s.slot_states()
    assert states[3] == "error"
    assert states[0] == "armed" and states[1] == "armed"


def test_press_inject_failure_drops_target(svc):
    s, backend, _ = svc
    s.toggle_slot(0); s.toggle_slot(1); s.toggle_slot(2)
    failed = {"20"}
    orig = backend.send_button_press

    def flaky(wid, *a, **kw):
        if wid in failed:
            backend.calls.append(("press-fail", wid))
            return False
        return orig(wid, *a, **kw)

    backend.send_button_press = flaky
    _press(s, 500, 250)  # source "10"; targets "20" (fails) and "30" (ok)
    _release(s, 500, 250)
    releases = [c for c in backend.calls if c[0] == "release"]
    assert [r[1] for r in releases] == ["30"]  # failed target got no release


def test_press_uses_fresh_geometry_provider(svc):
    # The cached provider still has the target's OLD origin; the window
    # just moved. Gesture snapshots must come from the fresh provider or
    # every injection in the gesture is mismapped.
    s, backend, _ = svc
    s.toggle_slot(0); s.toggle_slot(1)
    fresh = {"10": (0, 0, 1000, 500), "20": (1200, 0, 1000, 500)}
    s._fresh_geometry_provider = lambda wid: fresh.get(wid)
    _press(s, 500, 250)
    presses = [c for c in backend.calls if c[0] == "press"]
    assert presses and presses[0][4] == 1200 + 500  # fresh origin, not 1100


def test_press_zero_size_fresh_geometry_ignored(svc):
    # A fresh query returning a zero-size source (mid-teardown) must not
    # divide by zero or start a gesture.
    s, backend, _ = svc
    s.toggle_slot(0); s.toggle_slot(1)
    fresh = {"10": (0, 0, 0, 0), "20": (1100, 0, 1000, 500)}
    s._fresh_geometry_provider = lambda wid: fresh.get(wid)
    _press(s, 500, 250)
    assert backend.calls == []


def test_press_zero_size_fresh_target_skipped(svc):
    # A zero-size TARGET (mid-teardown) is skipped, not injected at (0, 0);
    # healthy targets still receive the press.
    s, backend, _ = svc
    s.toggle_slot(0); s.toggle_slot(1); s.toggle_slot(2)
    fresh = {"10": (0, 0, 1000, 500), "20": (1100, 0, 0, 0),
             "30": (0, 600, 2000, 1000)}
    s._fresh_geometry_provider = lambda wid: fresh.get(wid)
    _press(s, 500, 250)
    presses = [c for c in backend.calls if c[0] == "press"]
    assert [p[1] for p in presses] == ["30"]


def test_capture_died_drains_and_errors(svc):
    s, backend, _ = svc
    s.toggle_slot(0); s.toggle_slot(1)
    _press(s, 500, 250)
    s.notify_capture_died()
    releases = [c for c in backend.calls if c[0] == "release"]
    assert len(releases) == 1  # drained
    states = s.slot_states()
    assert states[0] == "error" and states[1] == "error" and states[2] == "off"


def test_geometry_divergence_mid_gesture_drains(svc):
    # The live-resize pause path: gesture in flight, geometry diverges,
    # the next recompute must drain (and the later physical release no-op).
    s, backend, _ = svc
    s.toggle_slot(0); s.toggle_slot(1)
    _press(s, 500, 250)
    geoms_bad = {"10": (0, 0, 1000, 500), "20": (1100, 0, 1000, 800)}
    s._geometry_provider = lambda wid: geoms_bad.get(wid)
    s.recompute()
    releases = [c for c in backend.calls if c[0] == "release"]
    assert len(releases) == 1 and releases[0][7] == 1000  # drain @ press time
    _release(s, 600, 250)
    assert len([c for c in backend.calls if c[0] == "release"]) == 1


def test_capture_stops_when_group_deactivates(svc):
    s, backend, captures = svc
    s.toggle_slot(0); s.toggle_slot(1)
    assert captures[-1].started
    s.toggle_slot(1)  # group drops below 2
    assert not captures[-1].started
    s.toggle_slot(1)  # re-arm: a NEW capture generation starts
    assert captures[-1].started


def test_capture_death_is_sticky_until_user_action(svc):
    # After a capture death, periodic recomputes must NOT auto-restart or
    # clear the error (no service_error spam); a user action recovers.
    s, backend, captures = svc
    s.toggle_slot(0); s.toggle_slot(1)
    s.notify_capture_died(captures[-1])
    assert s.slot_states()[0] == "error"
    n = len(captures)
    s.recompute()  # geometry tick
    s.recompute()
    assert s.slot_states()[0] == "error"
    assert len(captures) == n  # no new capture spawned
    s.toggle_slot(1)  # user action clears the latch (and leaves the group)
    s.toggle_slot(1)  # rejoin: group re-forms
    assert s.slot_states()[0] == "active"


def test_stale_capture_death_does_not_kill_current(svc):
    # A previous generation dying late is a no-op for the service: the
    # detach site that orphaned it owns stopping it, and the current
    # healthy capture and the states stay untouched.
    s, backend, captures = svc
    s.toggle_slot(0); s.toggle_slot(1)
    current = captures[-1]
    stale = FakeCapture(lambda *a: None)
    stale.started = True
    s.notify_capture_died(stale)
    assert stale.started is True       # not ours to stop (owner does)
    assert current.started is True     # healthy capture untouched
    assert s.slot_states()[0] == "active"


def test_instant_dead_capture_treated_as_start_failure(svc):
    # start() succeeded but the thread died before publication: the starter
    # must treat it as a failure, stop it (ownership), and latch sticky.
    s, backend, captures = svc

    class InstantDeath:
        def __init__(self):
            self.stopped = False

        def start(self):
            return True

        def is_running(self):
            return False  # died between start() and publication

        def stop(self):
            self.stopped = True

    dead_caps = []

    def factory(cb):
        c = InstantDeath()
        dead_caps.append(c)
        return c

    s._capture_factory = factory
    s.toggle_slot(0); s.toggle_slot(1)
    assert s.slot_states()[0] == "error"        # latched as failure
    assert dead_caps and dead_caps[0].stopped   # starter owned the stop
    s.recompute()
    assert len(dead_caps) == 1                  # sticky: no restart spam


def test_dead_capture_at_recompute_latches_no_restart(svc):
    # A geometry tick noticing the capture is dead BEFORE on_died arrives
    # must latch the failure (no silent restart); the late death
    # notification is then reclaim-only (current is None).
    s, backend, captures = svc
    s.toggle_slot(0); s.toggle_slot(1)
    gen1 = captures[-1]
    gen1.started = False  # died; nobody has been told yet
    n = len(captures)
    s.recompute()
    assert s.slot_states()[0] == "error"
    assert len(captures) == n          # no new generation spawned
    states_before = s.slot_states()
    s.notify_capture_died(gen1)        # late notification: reclaim only
    assert s.slot_states() == states_before


def test_stale_generation_events_are_gated(svc):
    # Events from a replaced generation's stream must never inject; only
    # the currently published generation's callback flows.
    s, backend, captures = svc
    s.toggle_slot(0); s.toggle_slot(1)
    gen1 = captures[-1]
    s.notify_capture_died(gen1)        # death + recovery -> generation 2
    s.toggle_slot(1); s.toggle_slot(1)
    gen2 = captures[-1]
    assert gen2 is not gen1 and gen2.started
    backend.calls.clear()
    gen1.on_event("press", 500, 250, 0, 1000)  # zombie stream: gated
    assert backend.calls == []
    gen2.on_event("press", 500, 250, 0, 1000)  # current stream: flows
    assert [c[0] for c in backend.calls] == ["press"]


# ── hover motion forwarding (no button held) ───────────────────────────


@pytest.fixture
def hover_svc(monkeypatch):
    """Like svc, but with a call-counting authoritative resolver and a
    controllable clock. Yields (service, backend, resolver_calls, clock)."""
    geoms = {
        "10": (0, 0, 1000, 500),
        "20": (1100, 0, 1000, 500),
        "30": (0, 600, 2000, 1000),
    }
    backend = FakeBackend()
    resolver_calls = []

    def resolver(rx, ry, wids):
        resolver_calls.append((rx, ry))
        return next(
            (w for w in wids
             if geoms.get(w)
             and geoms[w][0] <= rx < geoms[w][0] + geoms[w][2]
             and geoms[w][1] <= ry < geoms[w][1] + geoms[w][3]), None)

    clock = {"t": 100.0}
    monkeypatch.setattr("services.click_sync_service.monotonic",
                        lambda: clock["t"])
    s = ClickSyncService(
        slot_window_resolver=lambda slot: {0: "10", 1: "20", 2: "30"}.get(slot),
        geometry_provider=lambda wid: geoms.get(wid),
        source_resolver=resolver,
        backend=backend,
        capture_factory=lambda on_event: FakeCapture(on_event),
    )
    s.set_enabled(True)
    s.toggle_slot(0)
    s.toggle_slot(1)
    assert s.slot_states()[0] == "active"
    yield s, backend, resolver_calls, clock
    s.shutdown()


def _hover(s, x, y, t=2000):
    s._on_capture_event("motion", x, y, 0, t)


def test_hover_inside_member_forwards_mapped_motion(hover_svc):
    s, backend, _, _ = hover_svc
    _hover(s, 500, 250)  # center of "10" -> center of "20"
    motions = [c for c in backend.calls if c[0] == "motion"]
    assert len(motions) == 1
    kind, wid, x, y, rx, ry, state, t = motions[0]
    assert wid == "20"
    assert (x, y) == (500, 250)
    assert (rx, ry) == (1100 + 500, 0 + 250)
    assert state == 0          # unclicked: captured state passes through
    assert t == 2000


def test_hover_ignored_when_group_not_active(hover_svc):
    s, backend, _, _ = hover_svc
    s.toggle_slot(1)  # back to a single armed member
    backend.calls.clear()
    _hover(s, 500, 250)
    assert backend.calls == []


def test_hover_outside_members_ignored(hover_svc):
    s, backend, resolver_calls, _ = hover_svc
    _hover(s, 5000, 5000)
    assert backend.calls == []
    assert resolver_calls == []  # rect miss: no authoritative call either


def test_hover_same_window_confirms_once_then_reconfirms_after_interval(hover_svc):
    s, backend, resolver_calls, clock = hover_svc
    _hover(s, 100, 100)
    clock["t"] += 0.05  # past coalesce, inside confirm interval
    _hover(s, 120, 100)
    assert len(resolver_calls) == 1   # latched: no second confirm
    assert len([c for c in backend.calls if c[0] == "motion"]) == 2
    clock["t"] += 0.30  # past HOVER_CONFIRM_S
    _hover(s, 140, 100)
    assert len(resolver_calls) == 2   # periodic re-confirm


def test_hover_confirm_rejection_blocks_forwarding(hover_svc, monkeypatch):
    s, backend, _, clock = hover_svc
    errors = []
    s.service_error.connect(errors.append)
    monkeypatch.setattr(s, "_source_resolver", lambda rx, ry, wids: None)
    _hover(s, 500, 250)
    clock["t"] += 0.05
    _hover(s, 520, 250)
    assert [c for c in backend.calls if c[0] == "motion"] == []
    assert errors == []  # best-effort: never latches service error
    assert s.slot_states()[0] == "active"


def test_hover_gesture_takes_precedence(hover_svc):
    s, backend, resolver_calls, clock = hover_svc
    _hover(s, 500, 250)
    confirms_before = len(resolver_calls)
    clock["t"] += 0.05
    _press(s, 500, 250)               # gesture begins (resolver call: press)
    clock["t"] += 0.05
    s._on_capture_event("motion", 510, 250, 256, 2100)  # held motion
    # Held motion goes through the gesture path: no hover confirm happens.
    assert len(resolver_calls) == confirms_before + 1  # press only
    held = [c for c in backend.calls if c[0] == "motion" and c[6] == 256]
    assert len(held) == 1


def test_hover_echo_guard_duplicate_wid_skipped():
    geoms = {"10": (0, 0, 1000, 500)}
    backend = FakeBackend()
    s = ClickSyncService(
        slot_window_resolver=lambda slot: {0: "10", 1: "10"}.get(slot),
        geometry_provider=lambda wid: geoms.get(wid),
        source_resolver=lambda rx, ry, wids: "10",
        backend=backend,
        capture_factory=lambda on_event: FakeCapture(on_event),
    )
    try:
        s.set_enabled(True)
        s.toggle_slot(0)
        s.toggle_slot(1)
        _hover(s, 500, 250)
        assert [c for c in backend.calls if c[0] == "motion"] == []
    finally:
        s.shutdown()


# ── hover flush path (no real-time timers) ────────────────────────────


def test_hover_flush_never_calls_resolver(hover_svc):
    # The trailing flush runs on a throwaway timer thread. The production
    # resolver opens a per-thread X Display, so the flush must never call
    # it. For a latched candidate (same slot/wid) the flush skips the
    # periodic re-confirm; the sample still lands.
    s, backend, resolver_calls, clock = hover_svc
    _hover(s, 100, 100)                  # latches "10" (1 resolver call)
    clock["t"] += 0.001
    _hover(s, 130, 100, t=2001)          # pending + timer scheduled
    t = s._hover_flush_timer
    t.cancel()                           # drive the flush ourselves
    clock["t"] += 1.0                    # confirm interval long elapsed
    s._hover_flush(t)
    assert len(resolver_calls) == 1      # flush skipped the re-confirm
    motions = [c for c in backend.calls if c[0] == "motion"]
    assert motions[-1][2:4] == (130, 100)  # but the sample still landed


def test_hover_flush_drops_unlatched_candidate(hover_svc):
    # A pending sample that lands over a *different* member window (not the
    # latched source) must be dropped by the flush; no confirm call either.
    s, backend, resolver_calls, clock = hover_svc
    _hover(s, 100, 100)                  # latches "10"
    clock["t"] += 0.001
    _hover(s, 1500, 100, t=2001)         # pending sample over "20": unlatched
    t = s._hover_flush_timer
    t.cancel()
    before = len(resolver_calls)
    s._hover_flush(t)
    assert len(resolver_calls) == before                 # no confirm
    motions = [c for c in backend.calls if c[0] == "motion"]
    assert all(m[1] == "20" for m in motions)            # only the latched emits
    assert len(motions) == 1                             # the dropped sample never forwarded


def test_hover_member_to_member_candidate_change_reconfirms(hover_svc):
    # Moving the cursor from one member to another on the MAIN (non-flush)
    # path must trigger an authoritative re-confirm because the candidate
    # changed, even inside HOVER_CONFIRM_S.
    # Geometry: "10"=(0,0,1000,500), "20"=(1100,0,1000,500).
    # Point (1600,250) is inside "20" at rel (0.5,0.5) -> maps to "10"
    # client (500,250).
    s, backend, resolver_calls, clock = hover_svc
    _hover(s, 500, 250)                  # latch "10" (1 confirm)
    clock["t"] += 0.05                   # inside HOVER_CONFIRM_S
    _hover(s, 1600, 250, t=2001)         # cursor now over member "20"
    assert len(resolver_calls) == 2      # candidate change forced a confirm
    last = [c for c in backend.calls if c[0] == "motion"][-1]
    assert last[1] == "10"               # target flipped: source is now "20"
