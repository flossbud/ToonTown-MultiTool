"""Tests for utils.image_blur."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _checker_pixmap(w: int, h: int) -> QPixmap:
    """Half-red half-blue split pixmap with a sharp edge at x = w/2."""
    pix = QPixmap(w, h)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.fillRect(0, 0, w // 2, h, QColor("#ff0000"))
    p.fillRect(w // 2, 0, w - w // 2, h, QColor("#0000ff"))
    p.end()
    return pix


def test_blur_returns_same_size(qapp):
    from utils.image_blur import gaussian_blur_pixmap
    src = _checker_pixmap(200, 100)
    out = gaussian_blur_pixmap(src, radius=8)
    assert out.size() == src.size()


def test_blur_softens_sharp_edge(qapp):
    """The center column of the source pixmap is a sharp red/blue
    boundary. After blurring, the pixel at that boundary must have
    non-zero red AND non-zero blue (a true mix)."""
    from utils.image_blur import gaussian_blur_pixmap
    src = _checker_pixmap(200, 100)
    out = gaussian_blur_pixmap(src, radius=8)
    img = out.toImage()
    mid_x = 200 // 2
    mid_y = 100 // 2
    px = img.pixelColor(mid_x, mid_y)
    assert px.red() > 20, f"expected blurred red presence, got R={px.red()}"
    assert px.blue() > 20, f"expected blurred blue presence, got B={px.blue()}"


def test_blur_zero_radius_returns_visually_similar(qapp):
    """Radius 0 must not crash and must return a pixmap of the same
    size (we accept either a no-op copy or a trivial 0-pass blur)."""
    from utils.image_blur import gaussian_blur_pixmap
    src = _checker_pixmap(100, 50)
    out = gaussian_blur_pixmap(src, radius=0)
    assert out.size() == src.size()
