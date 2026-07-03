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
