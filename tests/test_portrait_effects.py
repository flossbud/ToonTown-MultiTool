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


def test_build_silhouette_shadow_pixmap_returns_at_least_source_size(qt_app):
    """Shadow pixmap is at least the source size; may grow to accommodate
    blur padding."""
    from PySide6.QtGui import QColor
    from utils.portrait_effects import build_silhouette_shadow_pixmap
    src = _make_disk_pixmap(32)
    out = build_silhouette_shadow_pixmap(src, QColor("#000000"), 4)
    assert out.width() >= src.width()
    assert out.height() >= src.height()


def test_build_silhouette_shadow_pixmap_uses_supplied_color(qt_app):
    """The shadow body should be the supplied color, not black-by-default."""
    from PySide6.QtGui import QColor
    from utils.portrait_effects import build_silhouette_shadow_pixmap
    src = _make_disk_pixmap(32)
    out = build_silhouette_shadow_pixmap(src, QColor("#0000ff"), 0)
    img = out.toImage()
    # With blur=0 the shadow alpha matches the source disk exactly.
    # Sample the center pixel which is inside the source disk.
    cx = out.width() // 2
    cy = out.height() // 2
    px = img.pixelColor(cx, cy)
    assert px.alpha() > 200
    assert px.blue() > 200
    assert px.red() < 80
    assert px.green() < 80


def test_build_silhouette_shadow_pixmap_has_alpha_falloff_with_blur(qt_app):
    """With nonzero blur, alpha falls off outside the source's hard edge
    instead of cutting cleanly to zero."""
    from PySide6.QtGui import QColor
    from utils.portrait_effects import build_silhouette_shadow_pixmap
    src = _make_disk_pixmap(32)
    out = build_silhouette_shadow_pixmap(src, QColor("#000000"), 6)
    img = out.toImage()
    # Find a pixel outside the source disk's bounds but within the blur
    # radius. The disk lives at src coords (8..24); after the shadow
    # builder centers the source in the larger output, the disk's left
    # edge is at (out.width() - 32) / 2 + 8. Sample 4px to its left.
    pad_x = (out.width() - 32) // 2
    sample_x = pad_x + 8 - 4
    sample_y = out.height() // 2
    if 0 <= sample_x < out.width():
        a = img.pixelColor(sample_x, sample_y).alpha()
        assert 0 < a < 255  # softened, not fully opaque nor zero


def test_build_silhouette_shadow_pixmap_returns_transparent_when_source_empty(qt_app):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QPixmap
    from utils.portrait_effects import build_silhouette_shadow_pixmap
    pm = QPixmap(16, 16)
    pm.fill(Qt.transparent)
    out = build_silhouette_shadow_pixmap(pm, QColor("#000000"), 4)
    img = out.toImage()
    # Every pixel transparent.
    for y in range(out.height()):
        for x in range(out.width()):
            assert img.pixelColor(x, y).alpha() == 0


def test_build_silhouette_shadow_pixmap_halo_not_clipped_at_source_edge(qt_app):
    """A source with alpha flush against the pixmap edge should still produce
    a visible halo in the pad zone — the blur must not be clipped by the
    scene boundary. Regression test for the `source_rect = item.boundingRect()`
    bug that silently clipped halo into negative scene coords."""
    from PySide6.QtGui import QColor, QPixmap
    from utils.portrait_effects import build_silhouette_shadow_pixmap

    # Fully opaque pixmap — alpha touches all four edges.
    pm = QPixmap(32, 32)
    pm.fill(QColor(255, 0, 0, 255))
    blur_px = 8
    out = build_silhouette_shadow_pixmap(pm, QColor("#0000ff"), blur_px)
    img = out.toImage()
    # Inside the pad zone (x=2 is well left of the source area which starts
    # at x=blur_px=8), the halo must produce some alpha. Buggy code returns
    # 0 here because the halo into negative scene coords is clipped.
    a = img.pixelColor(2, out.height() // 2).alpha()
    assert a > 0, (
        f"blur halo must extend into the pad zone for edge-flush content "
        f"(alpha at x=2 was {a})"
    )
