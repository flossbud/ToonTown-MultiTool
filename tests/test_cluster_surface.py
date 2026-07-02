"""Tests for ClusterSurface: the single always-mapped translucent cluster window.

ClusterSurface subclasses OverlaySurface to inherit the managed keep-above,
non-activating top-level plumbing, and adds ONE thing: a mandatory full-rect
transparent SOURCE-CLEAR paintEvent so the single ARGB top-level can never
flash a stale/opaque square on resize/partial-update (the EmblemSurface bug).

Run with:
    TTMT_NO_VENV_REEXEC=1 QT_QPA_PLATFORM=offscreen ./venv/bin/python -m pytest tests/test_cluster_surface.py -q
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt, QPoint, QRect
from PySide6.QtGui import QImage, QPainter, QColor
from PySide6.QtWidgets import QApplication, QWidget

from utils.overlay.cluster_surface import ClusterSurface, PanelSurface, RadialSurface


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


# ---------------------------------------------------------------------------
# Flags / attributes (inherited from OverlaySurface)
# ---------------------------------------------------------------------------

def test_wm_window_types_dock_cluster_osd_chrome(qapp):
    """The cluster is a DOCK (clamp-exempt, over the games, never animated);
    the radial + panel are KDE OSD - the ONLY type that simultaneously (a)
    sits in a layer KWin's internal click-raise cannot cross (so the cluster's
    internal dim can never cover the ring/panel), (b) is NOT matched by the
    slidingnotifications effect whose queued per-move displace animations
    painted the ring traveling in from a stale position (NOTIFICATION and
    CRITICAL_NOTIFICATION both are matched - live-bisected + source-verified),
    and (c) keeps the fit-to-desktop move-clamp exemption. DISPROVEN (do not
    revisit): dock+keep-above layering, WM_TRANSIENT_FOR vs internal raise."""
    assert ClusterSurface.WM_WINDOW_TYPE == "_NET_WM_WINDOW_TYPE_DOCK"
    assert RadialSurface.WM_WINDOW_TYPE == "_KDE_NET_WM_WINDOW_TYPE_ON_SCREEN_DISPLAY"
    assert PanelSurface.WM_WINDOW_TYPE == "_KDE_NET_WM_WINDOW_TYPE_ON_SCREEN_DISPLAY"


def test_cluster_surface_flags_and_translucent(qapp):
    s = ClusterSurface()
    flags = s.windowFlags()
    assert flags & Qt.FramelessWindowHint
    assert flags & Qt.WindowStaysOnTopHint
    # MANAGED by default (no override-redirect): keep-above beats the games but
    # stays below the compositor's system layers (screenshot UI etc.).
    assert not (flags & Qt.X11BypassWindowManagerHint)
    # The window TYPE (masked) must be plain Qt.Window, NOT Qt.Tool, so the
    # cluster window survives the main window's minimize.
    assert (flags & Qt.WindowType_Mask) == Qt.Window
    assert s.testAttribute(Qt.WA_TranslucentBackground)


# ---------------------------------------------------------------------------
# Mandatory source-clear paintEvent
# ---------------------------------------------------------------------------

def test_cluster_surface_source_clears_backing(qapp):
    """ClusterSurface must SOURCE-clear its whole rect to transparent on every
    paint, so the single ARGB top-level's unpainted regions are written to the
    native backing and can never flash a stale opaque square on resize. Simulated
    by rendering onto a pre-filled OPAQUE black target: the paint must overwrite
    both corners transparent (alpha 0). A plain OverlaySurface (paints nothing)
    would leave them opaque."""
    s = ClusterSurface()
    s.resize(40, 40)
    img = QImage(40, 40, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor(0, 0, 0, 255))            # stale opaque backing
    p = QPainter(img)
    s.render(p, QPoint(0, 0))                 # must source-clear its rect transparent
    p.end()
    assert img.pixelColor(0, 0).alpha() == 0
    assert img.pixelColor(39, 39).alpha() == 0


def test_cluster_surface_clear_preserves_child(qapp):
    """The parent's source-clear must NOT erase a hosted child's painting: a stub
    child's opaque center survives, while the corners stay transparent."""

    class _Center(QWidget):
        def paintEvent(self, ev):
            pp = QPainter(self)
            pp.fillRect(QRect(10, 10, 20, 20), QColor(255, 0, 0, 255))  # opaque center
            pp.end()

    s = ClusterSurface()
    child = _Center()
    s.host(child)
    s.resize(40, 40)                          # apply the full-bleed layout
    img = QImage(40, 40, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor(0, 0, 0, 255))
    p = QPainter(img)
    s.render(p, QPoint(0, 0))
    p.end()
    assert img.pixelColor(20, 20).alpha() == 255   # child center preserved over the clear
    assert img.pixelColor(0, 0).alpha() == 0       # corner cleared transparent


# ---------------------------------------------------------------------------
# RadialSurface inherits the SAME mandatory source-clear
# ---------------------------------------------------------------------------

def test_radial_surface_source_clears_backing(qapp):
    """RadialSurface is the radial menu's own source-cleared top-level and MUST
    inherit ClusterSurface's mandatory full-rect transparent source-clear, so the
    resizing radial window can never flash a stale opaque square (the EmblemSurface
    bug). Same probe as the cluster surface: rendering onto a pre-filled OPAQUE black
    target must overwrite both corners transparent (alpha 0)."""
    s = RadialSurface()
    s.resize(40, 40)
    img = QImage(40, 40, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor(0, 0, 0, 255))            # stale opaque backing
    p = QPainter(img)
    s.render(p, QPoint(0, 0))                 # must source-clear its rect transparent
    p.end()
    assert img.pixelColor(0, 0).alpha() == 0
    assert img.pixelColor(39, 39).alpha() == 0


# ---------------------------------------------------------------------------
# PanelSurface inherits the SAME mandatory source-clear
# ---------------------------------------------------------------------------

def test_panel_surface_source_clears_backing(qapp):
    """PanelSurface is the portable Settings panel's own source-cleared top-level
    and MUST inherit ClusterSurface's mandatory full-rect transparent source-clear,
    so the resizing panel window can never flash a stale opaque square (the
    EmblemSurface bug). Same probe as the cluster + radial surfaces: rendering onto
    a pre-filled OPAQUE black target must overwrite both corners transparent
    (alpha 0)."""
    s = PanelSurface()
    s.resize(40, 40)
    img = QImage(40, 40, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor(0, 0, 0, 255))            # stale opaque backing
    p = QPainter(img)
    s.render(p, QPoint(0, 0))                 # must source-clear its rect transparent
    p.end()
    assert img.pixelColor(0, 0).alpha() == 0
    assert img.pixelColor(39, 39).alpha() == 0


# ---------------------------------------------------------------------------
# Transform-scaled hosting (host_scaled / set_cluster_scale / release)
# ---------------------------------------------------------------------------

def _scaled_setup(qapp):
    """A ClusterSurface hosting a 400x300 stub host with an off-center emblem
    center (110, 90) under the SCALE_MAX envelope. Returns (surface, host)."""
    from utils.overlay.cluster_geometry import envelope_for
    from utils.overlay.scale import SCALE_MAX
    host = QWidget()
    host.setFixedSize(400, 300)
    size, pivot = envelope_for((400, 300), (110, 90), SCALE_MAX)
    s = ClusterSurface()
    s.host_scaled(host, (110, 90), pivot, size, initial_scale=1.0)
    return s, host


def test_host_scaled_embeds_borrowed_host_in_proxy(qapp):
    s, host = _scaled_setup(qapp)
    view = s._cluster_view
    assert view is not None
    assert view.host() is host
    # The proxy actually holds the host (addWidget succeeded on the detached host).
    assert view._proxy is not None and view._proxy.widget() is host
    s.release()


def test_set_cluster_scale_drives_the_item_transform_only(qapp):
    """A scale change must be pure transform: the proxy item's scale changes,
    the HOST's widget geometry does NOT (no re-layout), and the surface itself
    is not resized by the call."""
    s, host = _scaled_setup(qapp)
    s.resize(700, 525)
    geom_before = QRect(s.geometry())
    host_size_before = host.size()
    s.set_cluster_scale(1.5)
    assert s._cluster_view._proxy.scale() == 1.5
    assert s.cluster_scale() == 1.5
    assert host.size() == host_size_before      # the 1.0 layout is untouched
    assert s.geometry() == geom_before          # no window resize on scale
    s.release()


def test_scaled_release_returns_host_undeleted_and_clears_constraints(qapp):
    """release() must un-own the borrowed host (parentless, alive) and clear the
    fixed-size clamp so the framed grid can re-fit it after restore."""
    s, host = _scaled_setup(qapp)
    out = s.release()
    assert out is host
    assert host.parent() is None
    assert s._cluster_view is None
    assert host.minimumSize().width() == 0 and host.minimumSize().height() == 0
    assert host.maximumSize().width() == 16777215
    # The host is still a live widget (not deleted): resizing it must not crash.
    host.resize(10, 10)


def test_scaled_close_never_deletes_borrowed_host(qapp):
    """The programmatic close() path must release the proxied host BEFORE Qt's
    destruction cascade (ownership contract): after close + deleteLater flush the
    host must still be alive."""
    import shiboken6
    s, host = _scaled_setup(qapp)
    s.close()
    s.deleteLater()
    qapp.processEvents()
    assert shiboken6.isValid(host)
    assert host.parent() is None


def test_plain_host_release_path_still_works_for_radial(qapp):
    """RadialSurface/PanelSurface keep the plain full-bleed hosting: host() then
    release() must round-trip through the base OverlaySurface path untouched."""
    s = RadialSurface()
    child = QWidget()
    s.host(child)
    assert child.parent() is s
    out = s.release()
    assert out is child and child.parent() is None


def test_emblem_center_lands_on_pivot_at_every_scale(qapp):
    """The rendering-side invariant behind the whole design: mapping the emblem
    rect through the proxy's sceneTransform must keep its CENTER on the pivot at
    every scale (this is what makes zoom judder-free without moving the window)."""
    from PySide6.QtCore import QRectF
    from utils.overlay.cluster_geometry import envelope_for
    from utils.overlay.scale import SCALE_MAX
    host = QWidget()
    host.setFixedSize(400, 300)
    size, pivot = envelope_for((400, 300), (110, 90), SCALE_MAX)
    s = ClusterSurface()
    s.host_scaled(host, (110, 90), pivot, size, initial_scale=1.0)
    proxy = s._cluster_view._proxy
    emblem_rect = QRectF(60, 40, 100, 100)      # center (110, 90) in host coords
    for scale in (0.5, 1.0, 1.75):
        s.set_cluster_scale(scale)
        mapped = proxy.sceneTransform().mapRect(emblem_rect)
        assert abs(mapped.center().x() - pivot[0]) < 1e-6
        assert abs(mapped.center().y() - pivot[1]) < 1e-6
        # And the mapped size is the true scaled size (uniform zoom).
        assert abs(mapped.width() - 100 * scale) < 1e-6
    s.release()


# ---------------------------------------------------------------------------
# Pre-map opacity stage (mapped-with-no-buffer composites black - probed)
# ---------------------------------------------------------------------------

class _OpacityRecordingBackend:
    """Minimal backend recording set_window_opacity; everything else no-ops."""
    def __init__(self):
        self.opacities: list = []
    def is_available(self):
        return True
    def set_window_opacity(self, window, opacity):
        self.opacities.append((window, float(opacity)))
    def __getattr__(self, name):
        return lambda *a, **k: None


def test_prepare_initial_state_stages_opacity_zero(qapp):
    """prepare_initial_state must write _NET_WM_WINDOW_OPACITY=0 pre-map: a
    mapped window with NO buffer composites as an OPAQUE BLACK rect on
    KWin/XWayland, and at a startup float launch the event loop's first paint
    (= first buffer) can be seconds after enter() maps the surface. Applies to
    the cluster AND the persistent radial/panel (inherited)."""
    for cls in (ClusterSurface, RadialSurface, PanelSurface):
        backend = _OpacityRecordingBackend()
        s = cls(backend=backend)
        s.prepare_initial_state()
        assert [o for w, o in backend.opacities if w is s] == [0.0], cls.__name__
        s.deleteLater()


def test_first_paint_lifts_opacity_stage_repaint_before_opacity(qapp):
    """The stage is lifted one loop turn AFTER the first real paint: repaint
    first (flushes a current buffer now that the window is exposed), THEN the
    opacity write - the taskbar rep's proven anti-stale-frame ordering."""
    backend = _OpacityRecordingBackend()
    s = ClusterSurface(backend=backend)
    events: list = []
    backend.set_window_opacity = lambda w, o: events.append(("opacity", float(o)))
    orig_repaint = s.repaint
    s.repaint = lambda: (events.append(("repaint",)), orig_repaint())[1]

    s.prepare_initial_state()
    assert events == [("opacity", 0.0)]
    s.resize(60, 40)
    s.show()
    s.repaint()                              # deterministic first paint
    for _ in range(10):                      # zero-timer fires next loop pass
        qapp.processEvents()
        if ("opacity", 1.0) in events:
            break
    assert events[-1] == ("opacity", 1.0)
    assert ("repaint",) in events[:-1]       # repaint preceded the 1.0 write
    assert events.count(("opacity", 1.0)) == 1
    s.hide()
    s.deleteLater()


def test_paint_without_prepare_never_touches_opacity(qapp):
    """A surface that was never opacity-staged (prepare_initial_state not
    called - e.g. legacy paths) must never emit opacity writes from painting:
    the lift is armed exclusively by the stage."""
    backend = _OpacityRecordingBackend()
    s = ClusterSurface(backend=backend)
    s.resize(60, 40)
    s.show()
    s.repaint()
    qapp.processEvents()
    assert backend.opacities == []
    s.hide()
    s.deleteLater()
