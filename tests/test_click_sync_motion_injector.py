"""The darwin motion-injector worker (_MotionInjector): the send_motion RPC
must never run on the capture thread with the service lock held (measured
~3ms x ~115/s = a third of the thread blocked mid-stream + lock convoys =
the live ghost hiccups). Newest-wins per target: a slow RPC drops stale
intermediates instead of building a backlog (the CP16 sampling law)."""
import sys
import threading
import time

import pytest

from services.click_sync_service import ClickSyncService, _MotionInjector


class _GatedBackend:
    """send_motion blocks until released; records every delivered call."""

    def __init__(self):
        self.calls = []
        self.gate = threading.Event()
        self.entered = threading.Event()

    def send_motion(self, *args, **kwargs):
        self.entered.set()
        self.gate.wait(timeout=5.0)
        self.calls.append(args)
        return True


def _wait(pred, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.005)
    return False


def test_newest_wins_per_target_drops_stale_intermediates():
    be = _GatedBackend()
    inj = _MotionInjector(be)
    try:
        inj.submit(("w1", 1, 1, 1, 1), {})
        assert be.entered.wait(timeout=5.0)   # worker blocked inside RPC #1
        inj.submit(("w1", 2, 2, 2, 2), {})    # superseded while blocked...
        inj.submit(("w1", 3, 3, 3, 3), {})    # ...by this newest sample
        be.gate.set()
        assert _wait(lambda: len(be.calls) == 2)
        assert be.calls[0][1] == 1            # the in-flight first send
        assert be.calls[1][1] == 3            # newest wins; 2 never sent
        time.sleep(0.05)
        assert len(be.calls) == 2
    finally:
        inj.stop()


def test_distinct_targets_all_delivered():
    be = _GatedBackend()
    be.gate.set()
    inj = _MotionInjector(be)
    try:
        inj.submit(("w1", 1, 1, 1, 1), {})
        inj.submit(("w2", 2, 2, 2, 2), {})
        assert _wait(lambda: len(be.calls) == 2)
        assert {c[0] for c in be.calls} == {"w1", "w2"}
    finally:
        inj.stop()


def test_backend_error_swallowed_worker_survives():
    class _Boom:
        def __init__(self):
            self.calls = 0

        def send_motion(self, *a, **k):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("helper died")
            return True

    be = _Boom()
    inj = _MotionInjector(be)
    try:
        inj.submit(("w1", 1, 1, 1, 1), {})
        assert _wait(lambda: be.calls == 1)
        inj.submit(("w2", 2, 2, 2, 2), {})
        assert _wait(lambda: be.calls == 2)   # still alive after the raise
    finally:
        inj.stop()


def test_diag_hook_receives_durations():
    seen = []

    class _Fast:
        def send_motion(self, *a, **k):
            return True

    inj = _MotionInjector(_Fast(), note_send=seen.append)
    try:
        inj.submit(("w1", 1, 1, 1, 1), {})
        assert _wait(lambda: len(seen) == 1)
        assert seen[0] >= 0.0
    finally:
        inj.stop()


def test_stop_terminates_worker():
    inj = _MotionInjector(_GatedBackend())
    inj.stop()
    assert _wait(lambda: not inj._thread.is_alive())


def test_service_send_motion_routes_through_injector_on_darwin(monkeypatch):
    svc = ClickSyncService.__new__(ClickSyncService)
    svc._backend = object()
    svc._diag_rates = None
    svc._motion_injector = None
    submitted = []

    class _FakeInjector:
        def __init__(self, backend, note_send=None):
            pass

        def submit(self, args, kwargs):
            submitted.append((args, kwargs))

    from services import click_sync_service as css
    monkeypatch.setattr(css, "_MotionInjector", _FakeInjector)
    monkeypatch.setattr(sys, "platform", "darwin")
    assert svc._send_motion_timed("w1", 1, 2, 3, 4, state=0, time=0) is True
    assert submitted == [(("w1", 1, 2, 3, 4), {"state": 0, "time": 0})]


def test_service_shutdown_stops_injector():
    from unittest.mock import MagicMock
    svc = ClickSyncService(
        slot_window_resolver=lambda s: None,
        geometry_provider=lambda w: None,
        source_resolver=lambda *a: None,
        backend=MagicMock(),
        capture_factory=lambda cb: MagicMock(),
    )
    stopped = []
    inj = MagicMock()
    inj.stop = lambda: stopped.append(1)
    svc._motion_injector = inj
    svc.shutdown()
    assert stopped == [1]
    assert svc._motion_injector is None
