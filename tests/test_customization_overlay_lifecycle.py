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


def test_panel_has_pinned_dimensions(qapp):
    from utils.widgets.customization_overlay import _Panel
    parent = QWidget()
    parent.resize(575, 770)
    panel = _Panel(parent)
    assert panel.PANEL_W == 543
    assert panel.PANEL_H == 738
    assert panel.HEADER_H == 44
    assert panel.FOOTER_H == 52


def test_panel_has_close_x_button(qapp):
    from utils.widgets.customization_overlay import _Panel
    panel = _Panel()
    assert panel.close_btn is not None
    assert panel.close_btn.text() == ""  # icon-only
    assert panel.close_btn.minimumWidth() == 28


def test_panel_has_footer_buttons(qapp):
    from utils.widgets.customization_overlay import _Panel
    panel = _Panel()
    assert panel.reset_btn is not None
    assert panel.reset_btn.text() == "Reset all"
    assert panel.cancel_btn is not None
    assert panel.cancel_btn.text() == "Cancel"
    assert panel.save_btn is not None
    assert panel.save_btn.text() == "Save"


def test_panel_pill_row_exists(qapp):
    from utils.widgets.customization_overlay import _Panel
    panel = _Panel()
    assert panel.pill_row is not None
    assert panel.section_stack is not None


def test_panel_emits_close_signal(qapp):
    """Clicking the close X emits close_requested."""
    from utils.widgets.customization_overlay import _Panel
    panel = _Panel()
    received = []
    panel.close_requested.connect(lambda: received.append(True))
    panel.close_btn.click()
    assert received == [True]


def test_panel_emits_cancel_signal(qapp):
    from utils.widgets.customization_overlay import _Panel
    panel = _Panel()
    received = []
    panel.cancel_requested.connect(lambda: received.append(True))
    panel.cancel_btn.click()
    assert received == [True]


def test_panel_emits_save_signal(qapp):
    from utils.widgets.customization_overlay import _Panel
    panel = _Panel()
    received = []
    panel.save_requested.connect(lambda: received.append(True))
    panel.save_btn.click()
    assert received == [True]


def test_panel_emits_reset_signal(qapp):
    from utils.widgets.customization_overlay import _Panel
    panel = _Panel()
    received = []
    panel.reset_requested.connect(lambda: received.append(True))
    panel.reset_btn.click()
    assert received == [True]
