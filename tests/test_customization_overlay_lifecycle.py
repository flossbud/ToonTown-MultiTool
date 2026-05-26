"""Lifecycle tests for ToonCustomizationOverlay.

Starts with _BackdropBlur in isolation; expanded as tasks land."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QWidget


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _solid_pixmap(w, h, hex_color):
    pix = QPixmap(w, h)
    pix.fill(QColor(hex_color))
    return pix


def test_backdrop_blur_exists(qapp):
    from utils.widgets.customization_overlay import _BackdropBlur
    parent = QWidget()
    parent.resize(400, 300)
    bd = _BackdropBlur(parent)
    assert bd.parentWidget() is parent


def test_backdrop_blur_accepts_source_pixmap(qapp):
    """set_source_pixmap stores a blurred copy of the input. The
    blurred pixmap dimensions match the input (helper preserves
    size)."""
    from utils.widgets.customization_overlay import _BackdropBlur
    parent = QWidget()
    parent.resize(200, 100)
    bd = _BackdropBlur(parent)
    src = _solid_pixmap(200, 100, "#888888")
    bd.set_source_pixmap(src)
    assert bd._blurred is not None
    assert bd._blurred.size() == src.size()


def test_backdrop_blur_dim_color_present(qapp):
    """The widget paints a 40 % black dim on top of the blurred
    pixmap. We can introspect the dim color directly."""
    from utils.widgets.customization_overlay import _BackdropBlur
    bd = _BackdropBlur()
    assert bd.DIM_COLOR.alpha() == int(0.40 * 255)
    assert bd.DIM_COLOR.red() == 0
    assert bd.DIM_COLOR.green() == 0
    assert bd.DIM_COLOR.blue() == 0
