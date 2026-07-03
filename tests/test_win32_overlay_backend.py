"""Win32 overlay backend: arbiter logic + platform seams (offscreen-safe).

The pywin32 glue is exercised live on the Windows box (probe ledger
docs/superpowers/specs/2026-07-03-win32-overlay-probe-ledger.md); these tests
pin everything that runs identically on all platforms: the cursor-region
arbiter's X-Shape-contract semantics, backend availability gating, the
taskbar-rep capability gate, and the dismiss-capture platform dispatch.
"""
import sys

import pytest
from PySide6.QtCore import QRect
from PySide6.QtGui import QRegion
from PySide6.QtWidgets import QWidget

from utils.overlay.backend import (
    NoOpOverlayBackend,
    OverlayBackend,
    get_overlay_backend,
)
from utils.overlay.cluster_controller import ClusterOverlayController
from utils.overlay.win32_backend import CursorRegionArbiter, Win32OverlayBackend


# ---------------------------------------------------------------------------
# CursorRegionArbiter (pure logic, fake ports)
# ---------------------------------------------------------------------------

class _Ports:
    """Injected OS ports: settable cursor, per-key origins, recorded applies."""

    def __init__(self):
        self.cursor = (0, 0)
        self.origins = {}   # key -> (x, y); missing/None = dead window
        self.applied = []   # every (key, transparent) the arbiter pushed

    def make(self):
        return CursorRegionArbiter(
            cursor_pos=lambda: self.cursor,
            window_origin=lambda k: self.origins.get(k),
            apply_transparent=lambda k, t: self.applied.append((k, t)),
        )


def _region():
    return QRegion(QRect(10, 10, 100, 100))


def test_set_region_cursor_outside_applies_transparent():
    p = _Ports()
    p.origins["w"] = (0, 0)
    p.cursor = (500, 500)
    arb = p.make()
    arb.set_region("w", _region())
    assert p.applied == [("w", True)]


def test_set_region_cursor_inside_applies_interactive():
    p = _Ports()
    p.origins["w"] = (0, 0)
    p.cursor = (50, 50)
    arb = p.make()
    arb.set_region("w", _region())
    assert p.applied == [("w", False)]


def test_tick_flips_only_on_boundary_crossings():
    p = _Ports()
    p.origins["w"] = (0, 0)
    p.cursor = (50, 50)
    arb = p.make()
    arb.set_region("w", _region())
    arb.tick()
    arb.tick()
    assert p.applied == [("w", False)]      # no re-apply while inside
    p.cursor = (500, 500)
    arb.tick()
    arb.tick()
    assert p.applied == [("w", False), ("w", True)]  # one flip on exit


def test_window_origin_offsets_the_hit_test():
    p = _Ports()
    p.origins["w"] = (100, 100)
    p.cursor = (150, 150)                    # local (50,50) -> inside
    arb = p.make()
    arb.set_region("w", _region())
    assert p.applied == [("w", False)]
    p.cursor = (105, 105)                    # local (5,5) -> outside (region@10+)
    arb.tick()
    assert p.applied[-1] == ("w", True)


def test_empty_region_is_static_transparent_and_needs_no_polling():
    p = _Ports()
    p.origins["w"] = (0, 0)
    arb = p.make()
    arb.set_region("w", QRegion())
    assert p.applied == [("w", True)]
    assert arb.needs_polling is False


def test_nonempty_region_needs_polling_until_cleared():
    p = _Ports()
    p.origins["w"] = (0, 0)
    arb = p.make()
    arb.set_region("w", _region())
    assert arb.needs_polling is True
    arb.clear("w")
    assert arb.needs_polling is False
    assert p.applied[-1] == ("w", False)     # clear restores interactivity


def test_clear_unknown_key_is_a_noop():
    p = _Ports()
    arb = p.make()
    arb.clear("nope")
    assert p.applied == []


def test_dead_window_is_evicted_on_registration():
    p = _Ports()                              # no origin recorded = dead
    arb = p.make()
    arb.set_region("w", _region())
    assert arb.needs_polling is False         # dropped, not retained
    assert p.applied == []


def test_dead_window_is_evicted_on_tick():
    p = _Ports()
    p.origins["w"] = (0, 0)
    p.cursor = (50, 50)
    arb = p.make()
    arb.set_region("w", _region())
    del p.origins["w"]                        # window destroyed mid-life
    arb.tick()
    assert arb.needs_polling is False


def test_raising_apply_port_never_propagates():
    def boom(_k, _t):
        raise RuntimeError("style failure")

    p = _Ports()
    p.origins["w"] = (0, 0)
    arb = CursorRegionArbiter(
        cursor_pos=lambda: p.cursor,
        window_origin=lambda k: p.origins.get(k),
        apply_transparent=boom,
    )
    arb.set_region("w", _region())            # must not raise
    arb.tick()


# ---------------------------------------------------------------------------
# Backend seams (run on every platform)
# ---------------------------------------------------------------------------

def test_backend_unavailable_off_windows():
    b = Win32OverlayBackend()
    if sys.platform != "win32":
        assert b.is_available() is False
        # And the shape entry points are safe no-ops without availability.
        b.apply_input_region(object(), QRegion())
        b.clear_input_region(object())


def test_wants_taskbar_rep_capability():
    assert OverlayBackend().wants_taskbar_rep() is True
    assert NoOpOverlayBackend().wants_taskbar_rep() is True
    assert Win32OverlayBackend().wants_taskbar_rep() is False


def test_set_window_opacity_clamps_and_delegates():
    class _Win:
        def __init__(self):
            self.values = []

        def setWindowOpacity(self, v):
            self.values.append(v)

    w = _Win()
    b = Win32OverlayBackend()
    b.set_window_opacity(w, 0.5)
    b.set_window_opacity(w, -3)
    b.set_window_opacity(w, 7)
    assert w.values == [0.5, 0.0, 1.0]


def test_get_overlay_backend_win32_kill_switch(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("TTMT_OVERLAY_WIN32", "0")
    assert isinstance(get_overlay_backend(), NoOpOverlayBackend)


def test_get_overlay_backend_win32_branch_falls_back_without_pywin32(monkeypatch):
    # On a Linux host the win32 module imports with win32gui=None, so the
    # branch must degrade to NoOp instead of raising.
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("TTMT_OVERLAY_WIN32", raising=False)
    backend = get_overlay_backend()
    if not backend.is_available():
        assert isinstance(backend, NoOpOverlayBackend)


# ---------------------------------------------------------------------------
# Controller integration seams
# ---------------------------------------------------------------------------

class _DecliningBackend(NoOpOverlayBackend):
    """Available backend that declines the taskbar rep (the win32 shape)."""

    def is_available(self) -> bool:
        return True

    def wants_taskbar_rep(self) -> bool:
        return False


def _controller(qapp, backend):
    return ClusterOverlayController(
        QWidget(),
        backend=backend,
        settings=None,
        surface_factory=lambda: None,
        card_provider=object(),
    )


def test_rep_gate_skips_when_backend_declines(qapp):
    ctrl = _controller(qapp, _DecliningBackend())
    ctrl._ensure_taskbar_rep()
    assert ctrl._taskbar_rep is None


class _RecordingCapture:
    """XRecordCapture-contract stand-in for the dismiss factory."""

    instances: list = []

    def __init__(self, on_event):
        self.on_event = on_event
        self.started = False
        self.stopped = False
        _RecordingCapture.instances.append(self)

    def start(self):
        self.started = True
        return True

    def stop(self):
        self.stopped = True


class _AvailableBackend(NoOpOverlayBackend):
    def is_available(self) -> bool:
        return True


def test_dismiss_capture_dispatch_picks_win32_twin(qapp, monkeypatch):
    _RecordingCapture.instances.clear()
    monkeypatch.setattr(sys, "platform", "win32")
    import utils.win32_mouse_capture as w32mc
    monkeypatch.setattr(w32mc, "Win32MouseCapture", _RecordingCapture)
    ctrl = _controller(qapp, _AvailableBackend())
    ctrl._start_radial_dismiss_capture()
    assert len(_RecordingCapture.instances) == 1
    assert _RecordingCapture.instances[0].started is True
    ctrl._stop_radial_dismiss_capture()
    assert _RecordingCapture.instances[0].stopped is True


def test_dismiss_capture_dispatch_skips_unsupported_platform(qapp, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    ctrl = _controller(qapp, _AvailableBackend())
    ctrl._start_radial_dismiss_capture()
    assert ctrl._radial_dismiss_capture is None


# ---------------------------------------------------------------------------
# Taskbar identity (Milestone B): surface behaviors + controller wiring
# ---------------------------------------------------------------------------

class _FakeCloseEvent:
    def __init__(self, spontaneous):
        self._spont = spontaneous
        self.accepted = None

    def spontaneous(self):
        return self._spont

    def ignore(self):
        self.accepted = False

    def accept(self):
        self.accepted = True

    def isAccepted(self):
        return bool(self.accepted)


def _process(qapp, ms=50):
    import time
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        qapp.processEvents()


def test_identity_spontaneous_close_quits_deferred(qapp):
    from utils.overlay.cluster_surface import ClusterSurface

    calls = []
    s = ClusterSurface(backend=NoOpOverlayBackend())
    s._on_spontaneous_close = lambda: calls.append(1)
    ev = _FakeCloseEvent(spontaneous=True)
    s.closeEvent(ev)
    assert ev.accepted is False          # the close itself is refused
    assert calls == []                   # callback is DEFERRED, not synchronous
    _process(qapp)
    assert calls == [1]
    s.deleteLater()


def test_spontaneous_close_without_callback_stays_refused(qapp):
    from utils.overlay.cluster_surface import ClusterSurface

    s = ClusterSurface(backend=NoOpOverlayBackend())
    ev = _FakeCloseEvent(spontaneous=True)
    s.closeEvent(ev)
    assert ev.accepted is False
    _process(qapp)                       # nothing pending must fire
    s.deleteLater()


def test_programmatic_close_still_goes_through(qapp):
    from utils.overlay.cluster_surface import ClusterSurface

    s = ClusterSurface(backend=NoOpOverlayBackend())
    s._on_spontaneous_close = lambda: (_ for _ in ()).throw(AssertionError)
    ev = _FakeCloseEvent(spontaneous=False)
    s.closeEvent(ev)
    assert ev.accepted is True
    s.deleteLater()


def test_identity_minimize_bounces(qapp):
    from PySide6.QtCore import Qt
    from utils.overlay.cluster_surface import ClusterSurface

    s = ClusterSurface(backend=NoOpOverlayBackend())
    s._bounce_minimize = True
    s.show()
    _process(qapp)
    s.setWindowState(Qt.WindowMinimized)
    _process(qapp, 100)
    assert s.isMinimized() is False      # bounced back
    s.hide()
    s.deleteLater()


def test_minimize_not_bounced_by_default(qapp):
    from PySide6.QtCore import Qt
    from utils.overlay.cluster_surface import ClusterSurface

    s = ClusterSurface(backend=NoOpOverlayBackend())
    s.show()
    _process(qapp)
    s.setWindowState(Qt.WindowMinimized)
    _process(qapp, 100)
    assert s.isMinimized() is True
    s.hide()
    s.deleteLater()


def test_enter_sets_taskbar_identity_when_backend_declines_rep(qapp):
    from tests.test_cluster_controller import _make

    ctrl, provider, window, created = _make(backend=_DecliningBackend())
    assert ctrl.enter() is True
    surface = created[0]
    assert getattr(surface, "WIN_TASKBAR_IDENTITY", False) is True
    assert surface.windowTitle() == "ToonTown MultiTool"
    assert getattr(surface, "_on_spontaneous_close", None) is not None
    assert getattr(surface, "_bounce_minimize", False) is True
    ctrl.leave()


def test_enter_leaves_identity_off_when_rep_wanted(qapp):
    from tests.test_cluster_controller import _make

    ctrl, provider, window, created = _make()   # NoOp backend: wants rep
    assert ctrl.enter() is True
    surface = created[0]
    assert getattr(surface, "WIN_TASKBAR_IDENTITY", False) is False
    ctrl.leave()


# ---------------------------------------------------------------------------
# Ghost click emblem parity
# ---------------------------------------------------------------------------

def test_ghost_click_on_emblem_disc_fires_menu_requested(qapp, monkeypatch):
    from PySide6.QtCore import QObject, QRect, Signal

    class _Emblem(QObject):
        menu_requested = Signal()

    ctrl = _controller(qapp, _AvailableBackend())
    emblem = _Emblem()
    fired = []
    emblem.menu_requested.connect(lambda: fired.append(1))
    ctrl._emblem = emblem
    monkeypatch.setattr(ctrl, "_visible_card_geoms", lambda: [])
    monkeypatch.setattr(ctrl, "_emblem_rect", lambda: QRect(100, 100, 50, 50))
    monkeypatch.setattr(ctrl, "_compute_window_rect",
                        lambda: QRect(1000, 1000, 400, 400))
    # Disc center = (1125, 1125), radius 25.
    ctrl._ghost_click_pass([(0, 1125, 1125)])
    assert fired == [1]
    # A batch with several emblem hits toggles at most once.
    ctrl._ghost_click_pass([(0, 1125, 1125), (1, 1120, 1120)])
    assert fired == [1, 1]
    # Corner of the rect but outside the disc: no fire.
    ctrl._ghost_click_pass([(0, 1102, 1102)])
    assert fired == [1, 1]
    # No emblem wired: never raises.
    ctrl._emblem = None
    ctrl._ghost_click_pass([(0, 1125, 1125)])
