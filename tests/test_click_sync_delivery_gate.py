"""The additive delivery-readiness gate (spec §3.5). Linux/Windows: no change."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from services.click_sync_service import ClickSyncService


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class _Cap:
    def __init__(self, cb):
        self.cb = cb
        self._run = False
        self.started = False

    def start(self):
        self._run = True
        self.started = True
        return True

    def stop(self):
        self._run = False

    def is_running(self):
        return self._run


# Click Sync needs >= 2 compatible members to reach "active", so the resolver maps
# TWO slots to same-aspect windows.
_TWO_MEMBERS = {0: "100", 1: "200"}


def _service(qapp, delivery_ready):
    caps = []
    svc = ClickSyncService(
        slot_window_resolver=lambda s: _TWO_MEMBERS.get(s),
        geometry_provider=lambda wid: (0, 0, 800, 600),   # same aspect -> compatible
        source_resolver=lambda rx, ry, wids: None,
        backend=object(),
        capture_factory=lambda cb: caps.append(_Cap(cb)) or caps[-1],
        delivery_ready=delivery_ready,
    )
    return svc, caps


def test_not_ready_blocks_active_and_reports_reason(qapp):
    errors = []
    svc, caps = _service(qapp, delivery_ready=lambda: (False, "no SkyLight symbols"))
    svc.service_error.connect(lambda m: errors.append(m), Qt.DirectConnection)
    svc.toggle_slot(0); svc.toggle_slot(1)
    svc.set_enabled(True)
    assert svc.slot_states()[0] == "error"
    assert caps == [] or caps[0].started is False    # capture never started
    assert errors and "no SkyLight symbols" in errors[-1]


def test_ready_allows_active_and_starts_capture(qapp):
    svc, caps = _service(qapp, delivery_ready=lambda: (True, None))
    svc.toggle_slot(0); svc.toggle_slot(1)
    svc.set_enabled(True)
    assert svc.slot_states()[0] == "active"
    assert caps and caps[0].started is True


def test_probe_exception_fails_closed(qapp):
    def boom():
        raise RuntimeError("kaboom")
    svc, caps = _service(qapp, delivery_ready=boom)
    svc.toggle_slot(0); svc.toggle_slot(1)
    svc.set_enabled(True)
    assert svc.slot_states()[0] == "error"            # fail-closed: exception != ready
    assert caps == [] or caps[0].started is False


def test_default_probe_is_always_ready(qapp):
    # No delivery_ready arg -> Linux/Windows behavior unchanged (goes active).
    caps = []
    svc = ClickSyncService(
        slot_window_resolver=lambda s: _TWO_MEMBERS.get(s),
        geometry_provider=lambda wid: (0, 0, 800, 600),
        source_resolver=lambda rx, ry, wids: None,
        backend=object(),
        capture_factory=lambda cb: caps.append(_Cap(cb)) or caps[-1],
    )
    svc.toggle_slot(0); svc.toggle_slot(1)
    svc.set_enabled(True)
    assert svc.slot_states()[0] == "active"


def test_mid_run_flip_to_not_ready_latches_error_on_recompute(qapp):
    # An engine that faults mid-run flips the probe -> the next recompute latches error
    # (transition c, eventual; the immediate press-path guard is exercised live in Task 9).
    state = {"ready": True}
    svc, caps = _service(qapp, delivery_ready=lambda: (state["ready"],
                                                       None if state["ready"] else "faulted mid-run"))
    svc.toggle_slot(0); svc.toggle_slot(1)
    svc.set_enabled(True)
    assert svc.slot_states()[0] == "active"
    state["ready"] = False
    svc.recompute()
    assert svc.slot_states()[0] == "error"


class _PressBackend:
    """First target press succeeds, then the engine faults so a LATER target's press fails
    - exercises the (c) sticky mid-gesture abort + the stranded-press release."""
    def __init__(self):
        self.presses, self.releases, self.faulted = [], [], False

    def send_button_press(self, wid, x, y, rx, ry, state=0, time=0):
        self.presses.append(wid)
        if len(self.presses) == 1:
            return True            # first target delivered
        self.faulted = True        # engine faults on the next target
        return False

    def send_button_release(self, wid, x, y, rx, ry, state=0, time=0):
        self.releases.append(wid)
        return True

    def send_motion(self, *a, **k):
        return True


_THREE_MEMBERS = {0: "100", 1: "200", 2: "300"}


def test_press_fault_releases_already_pressed_targets(qapp):
    # source = slot 0 ("100"); targets = slots 1 ("200") + 2 ("300"). 200 is pressed OK, then
    # the engine faults so 300's press fails -> the (c) sticky guard must RELEASE 200 (no
    # stranded button), stop capture, and fire service_error.
    be = _PressBackend()
    caps, errors = [], []
    svc = ClickSyncService(
        slot_window_resolver=lambda s: _THREE_MEMBERS.get(s),
        geometry_provider=lambda wid: (0, 0, 800, 600),
        source_resolver=lambda rx, ry, wids: "100",      # slot 0 is the source
        backend=be,
        capture_factory=lambda cb: caps.append(_Cap(cb)) or caps[-1],
        delivery_ready=lambda: (not be.faulted,
                                None if not be.faulted else "faulted mid-gesture"),
    )
    svc.service_error.connect(lambda m: errors.append(m), Qt.DirectConnection)
    svc.toggle_slot(0); svc.toggle_slot(1); svc.toggle_slot(2)
    svc.set_enabled(True)
    assert svc.slot_states()[0] == "active" and caps and caps[0].started
    caps[0].cb("press", 400, 300, 0, 0)                  # drive a press at the source
    assert be.presses == ["200", "300"]                  # both attempted (200 ok, 300 faulted)
    assert be.releases == ["200"]                        # already-pressed target RELEASED, not stranded
    assert errors and "faulted mid-gesture" in errors[-1]
    assert svc.slot_states()[0] == "error"


@pytest.fixture(autouse=True)
def _sync_motion_injection(monkeypatch):
    """darwin routes motion injection through a worker thread (the capture
    thread must never block on the ~3ms helper RPC while holding the
    service lock - live ghost-hiccup fix). These tests assert backend
    calls synchronously after driving events, so run the injector inline;
    the real worker is pinned by tests/test_click_sync_motion_injector.py."""
    from time import monotonic as _monotonic

    from services import click_sync_service as _css

    class _InlineInjector:
        def __init__(self, backend, note_send=None):
            self._backend = backend
            self._note = note_send

        def submit(self, args, kwargs):
            t0 = _monotonic()
            try:
                self._backend.send_motion(*args, **kwargs)
            except Exception:
                pass
            if self._note is not None:
                self._note(_monotonic() - t0)

        def stop(self):
            pass

    monkeypatch.setattr(_css, "_MotionInjector", _InlineInjector)
