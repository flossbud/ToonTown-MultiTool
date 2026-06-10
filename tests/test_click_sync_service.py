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


def test_motion_without_gesture_ignored(svc):
    s, backend, _ = svc
    s.toggle_slot(0); s.toggle_slot(1)
    s._on_capture_event("motion", 110, 100, 0, 1001)
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
    # A previous generation dying late must only reclaim ITS connections:
    # the current healthy capture and the states stay untouched.
    s, backend, captures = svc
    s.toggle_slot(0); s.toggle_slot(1)
    current = captures[-1]
    stale = FakeCapture(lambda *a: None)
    stale.started = True
    s.notify_capture_died(stale)
    assert stale.started is False      # reclaimed (stopped)
    assert current.started is True     # healthy capture untouched
    assert s.slot_states()[0] == "active"


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
