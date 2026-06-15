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
