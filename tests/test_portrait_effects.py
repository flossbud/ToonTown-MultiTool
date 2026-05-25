"""Tests for portrait_effects.build_silhouette_outline_pixmap and
build_silhouette_shadow_pixmap. Both are pure pixmap transforms."""

from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest


@pytest.fixture
def qt_app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


def _make_disk_pixmap(size: int = 32) -> "QPixmap":
    """A 32x32 pixmap with a solid red 16x16 disk in the center on a
    transparent background. Used as a stand-in for a toon pose."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QPainter, QPixmap
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#ff0000"))
    p.drawEllipse(size // 4, size // 4, size // 2, size // 2)
    p.end()
    return pm


def test_build_silhouette_outline_pixmap_returns_same_size(qt_app):
    from PySide6.QtGui import QColor
    from utils.portrait_effects import build_silhouette_outline_pixmap
    src = _make_disk_pixmap(32)
    out = build_silhouette_outline_pixmap(src, QColor("#00ff00"), 2)
    assert out.size() == src.size()


def test_build_silhouette_outline_pixmap_paints_color_around_alpha_edge(qt_app):
    """A pixel just outside the source disk (within the outline width)
    should be the outline color in the result."""
    from PySide6.QtGui import QColor
    from utils.portrait_effects import build_silhouette_outline_pixmap
    src = _make_disk_pixmap(32)
    out = build_silhouette_outline_pixmap(src, QColor("#00ff00"), 2)
    img = out.toImage()
    # Disk extends from (8,8) to (24,24). Pixel (7, 16) is just left of
    # the disk's leftmost edge, well within 2px outline width.
    px = img.pixelColor(7, 16)
    assert px.alpha() > 0
    # Allow Qt anti-aliasing slop on RGB by comparing dominant channel.
    assert px.green() > 200
    assert px.red() < 80
    assert px.blue() < 80


def test_build_silhouette_outline_pixmap_leaves_interior_transparent(qt_app):
    """A pixel deep inside the source disk should be transparent in the
    outline pixmap so that drawing the original pose on top doesn't
    pick up tinted alpha. The outline is a donut, not a solid silhouette."""
    from PySide6.QtGui import QColor
    from utils.portrait_effects import build_silhouette_outline_pixmap
    src = _make_disk_pixmap(32)
    out = build_silhouette_outline_pixmap(src, QColor("#00ff00"), 2)
    img = out.toImage()
    # Center of disk
    px = img.pixelColor(16, 16)
    assert px.alpha() == 0


def test_build_silhouette_outline_pixmap_returns_transparent_when_source_empty(qt_app):
    """An entirely transparent source produces an entirely transparent
    output (no halo of nothing)."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QPixmap
    from utils.portrait_effects import build_silhouette_outline_pixmap
    pm = QPixmap(16, 16)
    pm.fill(Qt.transparent)
    out = build_silhouette_outline_pixmap(pm, QColor("#00ff00"), 2)
    img = out.toImage()
    for y in range(out.height()):
        for x in range(out.width()):
            assert img.pixelColor(x, y).alpha() == 0
