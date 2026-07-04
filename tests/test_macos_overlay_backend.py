"""Offscreen unit suite for the macOS overlay backend.

Live NSWindow glue is validated on the real Mac against the probe ledger
(docs/superpowers/specs/2026-07-03-macos-overlay-probe-ledger.md); these tests
pin the platform-independent logic: availability gating (the cocoa-QPA law),
the factory branch + TTMT_OVERLAY_MACOS kill switch, the dpr=1.0 logical
region contract, the WM_WINDOW_TYPE -> NSWindow level mapping, the arbiter
invalidate semantics (native-window recreation), the cocoa panel realization
of OverlaySurface, and the darwin dismiss-capture dispatch.

Everything runs under the offscreen QPA, where is_available() is False by
construction - the same property that keeps every Float UI gate off in CI.
"""
import sys

import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QPainterPath, QRegion
from PySide6.QtWidgets import QWidget

from utils.overlay.backend import (
    NoOpOverlayBackend,
    get_overlay_backend,
)
from utils.overlay.cluster_controller import ClusterOverlayController
from utils.overlay.cursor_arbiter import CursorRegionArbiter
from utils.overlay.macos_backend import (
    CLUSTER_WINDOW_LEVEL,
    PANEL_WINDOW_LEVEL,
    MacOSOverlayBackend,
)


# ---------------------------------------------------------------------------
# Availability gating
# ---------------------------------------------------------------------------

def test_backend_unavailable_off_darwin(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert MacOSOverlayBackend().is_available() is False


def test_backend_unavailable_under_offscreen_qpa(qapp, monkeypatch):
    """The load-bearing cocoa law: sys.platform=='darwin' is NOT enough -
    under the offscreen QPA winId() is not an NSView and every gate must
    stay off."""
    monkeypatch.setattr(sys, "platform", "darwin")
    assert qapp.platformName() != "cocoa"  # offscreen in tests
    assert MacOSOverlayBackend().is_available() is False


def test_seam_methods_never_raise_when_unavailable(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    b = MacOSOverlayBackend()
    assert b.is_available() is False
    w = object()
    b.set_overlay_hints(w)
    b.set_initial_state(w)
    b.set_above(w)
    b.set_non_activating(w)
    b.set_rep_initial_state(w)
    b.set_skip_close_animation(w)
    b.apply_input_shape(w, QPainterPath(), 2.0)
    b.apply_input_region(w, QRegion())
    b.clear_input_region(w)


def test_wants_taskbar_rep_false():
    assert MacOSOverlayBackend().wants_taskbar_rep() is False


# ---------------------------------------------------------------------------
# Factory branch + kill switch
# ---------------------------------------------------------------------------

def test_get_overlay_backend_macos_kill_switch(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("TTMT_OVERLAY_MACOS", "0")
    assert isinstance(get_overlay_backend(), NoOpOverlayBackend)


def test_get_overlay_backend_macos_branch_available(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.delenv("TTMT_OVERLAY_MACOS", raising=False)
    monkeypatch.setattr(MacOSOverlayBackend, "is_available", lambda self: True)
    assert isinstance(get_overlay_backend(), MacOSOverlayBackend)


def test_get_overlay_backend_macos_falls_back_when_unavailable(qapp, monkeypatch):
    # Offscreen QPA -> is_available False -> factory degrades to NoOp.
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.delenv("TTMT_OVERLAY_MACOS", raising=False)
    assert isinstance(get_overlay_backend(), NoOpOverlayBackend)


# ---------------------------------------------------------------------------
# Input-shape contract: logical regions (dpr deliberately ignored)
# ---------------------------------------------------------------------------

def test_apply_input_shape_polygonizes_at_dpr_1(monkeypatch):
    monkeypatch.setattr(MacOSOverlayBackend, "is_available", lambda self: True)
    b = MacOSOverlayBackend()
    recorded = {}

    import utils.overlay.region as region_mod

    def fake_device_input_region(path, dpr):
        recorded["dpr"] = dpr
        return QRegion(QRect(0, 0, 10, 10))

    monkeypatch.setattr(region_mod, "device_input_region", fake_device_input_region)
    monkeypatch.setattr(
        b, "apply_input_region", lambda w, r: recorded.__setitem__("region", r))

    path = QPainterPath()
    path.addRect(0, 0, 50, 50)
    b.apply_input_shape(object(), path, 2.0)  # a Retina dpr must NOT scale
    assert recorded["dpr"] == 1.0
    assert not recorded["region"].isEmpty()


def test_set_window_opacity_clamps_and_delegates():
    class _Win:
        def __init__(self):
            self.values = []

        def setWindowOpacity(self, v):
            self.values.append(v)

    w = _Win()
    b = MacOSOverlayBackend()
    b.set_window_opacity(w, 0.5)
    b.set_window_opacity(w, -3)
    b.set_window_opacity(w, 7)
    assert w.values == [0.5, 0.0, 1.0]


# ---------------------------------------------------------------------------
# Level mapping (CP4: levels beat raise order)
# ---------------------------------------------------------------------------

def test_level_for_maps_window_type():
    class _Dock:
        WM_WINDOW_TYPE = "_NET_WM_WINDOW_TYPE_DOCK"

    class _Osd:
        WM_WINDOW_TYPE = "_NET_WM_KDE_WINDOW_TYPE_ON_SCREEN_DISPLAY"

    class _Bare:
        pass

    assert MacOSOverlayBackend._level_for(_Dock()) == CLUSTER_WINDOW_LEVEL
    assert MacOSOverlayBackend._level_for(_Osd()) == PANEL_WINDOW_LEVEL
    # No attr -> the DOCK default, same as x11_backend's read.
    assert MacOSOverlayBackend._level_for(_Bare()) == CLUSTER_WINDOW_LEVEL
    assert PANEL_WINDOW_LEVEL > CLUSTER_WINDOW_LEVEL  # the invariant itself


# ---------------------------------------------------------------------------
# Arbiter invalidate (native-window recreation semantics)
# ---------------------------------------------------------------------------

class _Ports:
    def __init__(self):
        self.cursor = (0, 0)
        self.origins = {}
        self.applied = []

    def make(self):
        return CursorRegionArbiter(
            cursor_pos=lambda: self.cursor,
            window_origin=lambda k: self.origins.get(k),
            apply_transparent=lambda k, t: self.applied.append((k, t)),
        )


def _region():
    return QRegion(QRect(10, 10, 100, 100))


def test_invalidate_reapplies_after_native_recreation():
    """A recreated NSWindow resets to the OS default while the cache holds
    the old state; invalidate must force one correcting apply."""
    ports = _Ports()
    arb = ports.make()
    ports.origins["w"] = (0, 0)
    ports.cursor = (500, 500)          # outside -> transparent
    arb.set_region("w", _region())
    assert ports.applied == [("w", True)]
    arb.tick()                          # cache-first: no re-fire
    assert ports.applied == [("w", True)]
    arb.invalidate("w")                 # recreation: cache dropped, re-applied
    assert ports.applied == [("w", True), ("w", True)]


def test_invalidate_empty_region_reapplies_static_transparent():
    ports = _Ports()
    arb = ports.make()
    ports.origins["w"] = (0, 0)
    arb.set_region("w", QRegion())
    assert ports.applied == [("w", True)]
    arb.invalidate("w")
    assert ports.applied == [("w", True), ("w", True)]
    assert arb.needs_polling is False   # still static


def test_invalidate_unknown_key_is_a_noop():
    ports = _Ports()
    arb = ports.make()
    arb.invalidate("never-registered")
    assert ports.applied == []


def test_win32_reexport_is_the_shared_arbiter():
    from utils.overlay.win32_backend import CursorRegionArbiter as ReExported
    assert ReExported is CursorRegionArbiter


# ---------------------------------------------------------------------------
# Surface realization on cocoa (Qt.Tool -> NSPanel)
# ---------------------------------------------------------------------------

def test_surface_panel_realization_on_cocoa(qapp, monkeypatch):
    import utils.overlay.surface as surface_mod
    monkeypatch.setattr(surface_mod, "_use_nonactivating_panel", lambda: True)
    s = surface_mod.OverlaySurface(backend=NoOpOverlayBackend())
    assert (s.windowFlags() & Qt.WindowType_Mask) == Qt.Tool
    s.deleteLater()


def test_surface_stays_plain_window_off_cocoa(qapp, monkeypatch):
    import utils.overlay.surface as surface_mod
    monkeypatch.setattr(surface_mod, "_use_nonactivating_panel", lambda: False)
    s = surface_mod.OverlaySurface(backend=NoOpOverlayBackend())
    assert (s.windowFlags() & Qt.WindowType_Mask) == Qt.Window
    s.deleteLater()


def test_use_nonactivating_panel_false_off_darwin(monkeypatch):
    import utils.overlay.surface as surface_mod
    monkeypatch.setattr(sys, "platform", "linux")
    assert surface_mod._use_nonactivating_panel() is False


def test_use_nonactivating_panel_false_under_offscreen(qapp, monkeypatch):
    import utils.overlay.surface as surface_mod
    monkeypatch.setattr(sys, "platform", "darwin")
    assert surface_mod._use_nonactivating_panel() is False  # offscreen QPA


# ---------------------------------------------------------------------------
# Dismiss-capture dispatch (darwin twin)
# ---------------------------------------------------------------------------

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


def _controller(qapp, backend):
    return ClusterOverlayController(
        QWidget(),
        backend=backend,
        settings=None,
        surface_factory=lambda: None,
        card_provider=object(),
    )


def test_dismiss_capture_dispatch_picks_macos_twin(qapp, monkeypatch):
    _RecordingCapture.instances.clear()
    monkeypatch.setattr(sys, "platform", "darwin")
    import utils.macos_mouse_capture as mmc
    monkeypatch.setattr(mmc, "MacOSMouseCapture", _RecordingCapture)
    ctrl = _controller(qapp, _AvailableBackend())
    ctrl._start_radial_dismiss_capture()
    assert len(_RecordingCapture.instances) == 1
    assert _RecordingCapture.instances[0].started is True
    ctrl._stop_radial_dismiss_capture()
    assert _RecordingCapture.instances[0].stopped is True
