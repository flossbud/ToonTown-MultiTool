"""Darwin click-sync wiring: the source resolver + the platform gate (no PyObjC)."""
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


def test_darwin_wiring_builds_service_and_skips_ghost_cursors(monkeypatch):
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
            return (True, None)

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
        assert tab.ghost_cursor_controller is None         # ghost cursors OFF on darwin (spec §3.6)
        assert tab._click_sync_backend.mouse_delivery_ready() == (True, None)
        # the SAME EchoLedger instance must reach BOTH the backend and the capture, or the
        # marker-stripped-echo de-dup is broken (review touchpoint #1 #1).
        be_ledger = tab._click_sync_backend.ledger
        assert be_ledger is not None
        tab.click_sync_service._capture_factory(lambda *a: None)   # build a capture via the WIRED factory
        assert captures and captures[0].ledger is be_ledger        # identical instance
    finally:
        tab.input_service.shutdown()   # avoid the non-daemon InputService thread leak
