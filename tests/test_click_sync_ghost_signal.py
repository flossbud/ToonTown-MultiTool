"""ghost_pointer_event / ghost_clear emission tests (injected fakes).

Geometry fixture matches tests/test_click_sync_service.py: "10" and "20"
are same-size side-by-side windows, "30" is same-aspect at double size.
"""
import pytest

from services.click_sync_service import ClickSyncService


class FakeBackend:
    def __init__(self, fail_press_wids=()):
        self.calls = []
        self.fail_press_wids = set(fail_press_wids)

    def send_button_press(self, wid, x, y, root_x, root_y, button=1, state=0, time=0):
        self.calls.append(("press", wid, x, y, root_x, root_y, state, time))
        return wid not in self.fail_press_wids

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


GEOMS = {
    "10": (0, 0, 1000, 500),
    "20": (1100, 0, 1000, 500),
    "30": (0, 600, 2000, 1000),  # same aspect, double size
}


def _make_service(fail_press_wids=()):
    backend = FakeBackend(fail_press_wids)
    s = ClickSyncService(
        slot_window_resolver=lambda slot: {0: "10", 1: "20", 2: "30"}.get(slot),
        geometry_provider=lambda wid: GEOMS.get(wid),
        source_resolver=lambda rx, ry, wids: next(
            (w for w in wids
             if GEOMS.get(w)
             and GEOMS[w][0] <= rx < GEOMS[w][0] + GEOMS[w][2]
             and GEOMS[w][1] <= ry < GEOMS[w][1] + GEOMS[w][3]), None),
        backend=backend,
        capture_factory=lambda on_event: FakeCapture(on_event),
    )
    s.set_enabled(True)
    return s, backend


@pytest.fixture
def svc():
    s, backend = _make_service()
    events, clears = [], []
    s.ghost_pointer_event.connect(events.append)
    s.ghost_clear.connect(lambda: clears.append(True))
    yield s, backend, events, clears
    s.shutdown()


def test_press_emits_ghosts_for_delivered_targets(svc):
    s, _, events, _ = svc
    s.toggle_slot(0); s.toggle_slot(2)
    events.clear()
    s._on_capture_event("press", 500, 250, 0, 1000)   # center of "10"
    presses = [e for e in events if e[0] == "press"]
    # Center of double-size "30" in screen space: origin + mapped point.
    assert presses == [("press", [(2, 1000, 1100)])]


def test_hover_motion_emits_ghosts(svc):
    s, _, events, _ = svc
    s.toggle_slot(0); s.toggle_slot(1)
    events.clear()
    s._on_capture_event("motion", 500, 250, 0, 1000)  # state 0: hover path
    motions = [e for e in events if e[0] == "motion"]
    assert motions == [("motion", [(1, 1600, 250)])]


def test_gesture_motion_and_release_emit_ghosts(svc, monkeypatch):
    s, _, events, _ = svc
    s.toggle_slot(0); s.toggle_slot(1)
    clock = {"t": 100.0}
    monkeypatch.setattr("services.click_sync_service.monotonic",
                        lambda: clock["t"])
    events.clear()
    s._on_capture_event("press", 500, 250, 0, 1000)
    clock["t"] += 1.0
    s._on_capture_event("motion", 600, 250, 256, 1001)
    s._on_capture_event("release", 600, 250, 256, 1002)
    kinds = [e[0] for e in events]
    assert kinds == ["press", "motion", "release"]
    assert events[1] == ("motion", [(1, 1700, 250)])
    assert events[2] == ("release", [(1, 1700, 250)])


def test_source_slot_never_in_a_batch(svc):
    s, _, events, _ = svc
    s.toggle_slot(0); s.toggle_slot(1); s.toggle_slot(2)
    events.clear()
    s._on_capture_event("motion", 500, 250, 0, 1000)  # hover from "10"
    s._on_capture_event("press", 500, 250, 0, 2000)
    assert events  # both paths emitted something
    for _kind, points in events:
        assert all(slot != 0 for slot, _x, _y in points)


def test_failed_press_target_not_in_ghosts():
    s, _backend = _make_service(fail_press_wids=("20",))
    events = []
    s.ghost_pointer_event.connect(events.append)
    try:
        s.toggle_slot(0); s.toggle_slot(1); s.toggle_slot(2)
        events.clear()
        s._on_capture_event("press", 500, 250, 0, 1000)
        presses = [e for e in events if e[0] == "press"]
        # "20" (slot 1) failed injection and is not in the gesture; the
        # ghost batch must match the DELIVERED targets only.
        assert presses == [("press", [(2, 1000, 1100)])]
    finally:
        s.shutdown()


def test_clear_emitted_on_disable_and_membership_change(svc):
    s, _, _, clears = svc
    s.toggle_slot(0); s.toggle_slot(1)
    clears.clear()
    s.toggle_slot(1)                 # membership change
    assert clears
    clears.clear()
    s.set_enabled(False)             # master off
    assert clears


def test_drag_ghost_decoupled_from_injection_throttle(svc, monkeypatch):
    """The ghost emits on EVERY drag motion (display rate) while injection stays
    throttled to MOTION_COALESCE_S. Re-coupling them (one ghost per injected
    motion) would make the overlay choppy on a high-refresh monitor."""
    s, backend, events, _ = svc
    s.toggle_slot(0); s.toggle_slot(1)
    clock = {"t": 100.0}
    monkeypatch.setattr("services.click_sync_service.monotonic", lambda: clock["t"])
    s._on_capture_event("press", 500, 250, 0, 1000)
    events.clear(); backend.calls.clear()
    # Three drag motions at the SAME instant (2nd/3rd within MOTION_COALESCE_S).
    s._on_capture_event("motion", 600, 250, 256, 1001)
    s._on_capture_event("motion", 610, 250, 256, 1002)
    s._on_capture_event("motion", 620, 250, 256, 1003)
    ghost_motions = [e for e in events if e[0] == "motion"]
    injected = [c for c in backend.calls if c[0] == "motion"]
    assert len(ghost_motions) == 3        # ghost on every motion (display rate)
    assert len(injected) == 1             # injection throttled to one


def test_hover_ghost_decoupled_from_injection_throttle(svc, monkeypatch):
    """Same decoupling on the hover path: ghost every motion, injection throttled."""
    s, backend, events, _ = svc
    s.toggle_slot(0); s.toggle_slot(1)
    clock = {"t": 100.0}
    monkeypatch.setattr("services.click_sync_service.monotonic", lambda: clock["t"])
    events.clear(); backend.calls.clear()
    s._on_capture_event("motion", 500, 250, 0, 1000)   # latches hover source "10"
    s._on_capture_event("motion", 510, 250, 0, 1001)   # within COALESCE -> ghost only
    s._on_capture_event("motion", 520, 250, 0, 1002)
    ghost_motions = [e for e in events if e[0] == "motion"]
    injected = [c for c in backend.calls if c[0] == "motion"]
    assert len(ghost_motions) == 3
    assert len(injected) == 1


def test_press_does_not_emit_ghost_clear(svc):
    """A press resets hover state by direct assignment, NOT via
    _clear_hover_locked: ghosts must never blink off at gesture start. A
    refactor collapsing those assignments into _clear_hover_locked() would
    pass the rest of the suite while introducing a visible flicker."""
    s, _, _, clears = svc
    s.toggle_slot(0); s.toggle_slot(1)
    s._on_capture_event("motion", 500, 250, 0, 900)   # latch a hover source
    clears.clear()
    s._on_capture_event("press", 500, 250, 0, 1000)
    assert clears == []
