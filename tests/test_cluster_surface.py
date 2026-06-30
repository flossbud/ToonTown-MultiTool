"""Tests for ClusterSurface: the single always-mapped translucent cluster window.

ClusterSurface subclasses OverlaySurface to inherit the override-redirect,
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

from utils.overlay.cluster_surface import ClusterSurface, RadialSurface


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


# ---------------------------------------------------------------------------
# Flags / attributes (inherited from OverlaySurface)
# ---------------------------------------------------------------------------

def test_cluster_surface_flags_and_translucent(qapp):
    s = ClusterSurface()
    flags = s.windowFlags()
    assert flags & Qt.FramelessWindowHint
    assert flags & Qt.WindowStaysOnTopHint
    assert flags & Qt.X11BypassWindowManagerHint
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
