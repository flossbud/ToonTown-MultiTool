"""Darwin click-sync wiring: the source resolver + the platform gate (no PyObjC)."""
import pytest

import utils.macos_discovery as disc


def test_darwin_resolver_uses_active_source_window(monkeypatch):
    # The tab's darwin _cs_source_resolver delegates to active_source_window; verify
    # the delegate returns a member only when active + point-inside.
    monkeypatch.setattr(disc, "get_active_window_id", lambda: "77")
    monkeypatch.setattr(disc, "get_window_geometry_fresh", lambda w: (0, 0, 100, 100))
    assert disc.active_source_window(10, 10, ["77"]) == "77"
    assert disc.active_source_window(10, 10, ["55"]) is None     # active not a member
    monkeypatch.setattr(disc, "get_window_geometry_fresh", lambda w: (200, 200, 10, 10))
    assert disc.active_source_window(10, 10, ["77"]) is None     # point outside


def test_darwin_wiring_builds_service_and_ghost_cursors(monkeypatch):
    # INSTANTIATE the darwin branch with FAKES (not a source grep): pin darwin, stub the
    # macOS collaborators, build the real tab, and assert the wiring. Reuse the tab
    # builder from tests/test_click_sync_ui.py (the same construction + config isolation
    # those tests already use).
    import sys
    from tests.test_click_sync_ui import build_multitoon_tab
    monkeypatch.setattr(sys, "platform", "darwin")

    captures = []

    class _FakeBackend:
        def __init__(self):
            self.ledger = None
        def set_echo_ledger(self, ledger):
            self.ledger = ledger            # record the shared-ledger wiring call
        def mouse_delivery_ready(self):
            return (True, "darwin-probe")       # distinctive: proves THIS probe is the wired one

    class _FakeCapture:
        def __init__(self, on_event, on_died=None, ledger=None, **kw):
            self.on_event, self.on_died, self.ledger = on_event, on_died, ledger
            captures.append(self)
        def start(self):
            return True
        def stop(self):
            pass
        def is_running(self):
            return True

    monkeypatch.setattr("utils.macos_backend.MacOSBackend", lambda *a, **k: _FakeBackend())
    monkeypatch.setattr("utils.macos_mouse_capture.MacOSMouseCapture", _FakeCapture)
    monkeypatch.setattr("utils.macos_discovery.get_window_geometry_fresh", lambda w: (0, 0, 800, 600))
    monkeypatch.setattr("utils.macos_discovery.active_source_window",
                        lambda rx, ry, wids: (wids[0] if wids else None))

    tab = build_multitoon_tab(monkeypatch)
    try:
        assert tab.click_sync_service is not None          # darwin is wired, not excluded
        assert tab.ghost_cursor_controller is not None     # ghost cursors built on darwin (spike-proven 2026-06-15)
        # delivery_ready must be WIRED INTO the service, not just present on the backend: the
        # service's probe must return the BACKEND's distinctive value (the default always-ready
        # would be (True, None)), so a dropped `delivery_ready=` arg in _tab.py is caught.
        assert tab._click_sync_backend.mouse_delivery_ready() == (True, "darwin-probe")
        assert tab.click_sync_service._delivery_ready_fn() == (True, "darwin-probe")
        # the SAME EchoLedger instance must reach BOTH the backend and the capture, or the
        # marker-stripped-echo de-dup is broken.
        be_ledger = tab._click_sync_backend.ledger
        assert be_ledger is not None
        tab.click_sync_service._capture_factory(lambda *a: None)   # build a capture via the WIRED factory
        assert captures and captures[0].ledger is be_ledger        # identical instance
    finally:
        tab.input_service.shutdown()   # avoid the non-daemon InputService thread leak


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
