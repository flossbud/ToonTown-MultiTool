import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_backdrop_blur_actually_blurs_an_edge(qapp):
    # A solid fill would blur to itself; use a sharp red|blue edge and assert the
    # boundary becomes a blended pixel (proving a real blur, not a passthrough).
    from PySide6.QtGui import QColor, QPainter
    from utils.widgets.backdrop_blur import BackdropBlur
    src = QPixmap(80, 80)
    src.fill(Qt.red)
    p = QPainter(src)
    p.fillRect(40, 0, 40, 80, QColor(Qt.blue))   # right half blue
    p.end()
    b = BackdropBlur()
    b.set_source_pixmap(src)
    assert b._blurred is not None and not b._blurred.isNull()
    img = b._blurred.toImage()
    edge = img.pixelColor(40, 40)                 # at the former sharp boundary
    # blended: both channels present, neither pure red nor pure blue
    assert edge.red() > 0 and edge.blue() > 0
    assert edge != QColor(Qt.red) and edge != QColor(Qt.blue)


def test_backdrop_blur_null_source_clears(qapp):
    from utils.widgets.backdrop_blur import BackdropBlur
    b = BackdropBlur()
    b.set_source_pixmap(QPixmap(40, 40))
    b.set_source_pixmap(QPixmap())         # explicitly null
    assert b._blurred is None


def test_backdrop_blur_none_source_is_safe(qapp):
    from utils.widgets.backdrop_blur import BackdropBlur
    b = BackdropBlur()
    b.set_source_pixmap(QPixmap(40, 40))
    b.set_source_pixmap(None)              # None must be handled like null
    assert b._blurred is None


def test_backdrop_blur_opacity_property(qapp):
    from utils.widgets.backdrop_blur import BackdropBlur
    b = BackdropBlur()
    b.opacity = 0.5
    assert b.opacity == 0.5


def test_backdrop_blur_mouse_transparent_flag(qapp):
    from utils.widgets.backdrop_blur import BackdropBlur
    assert BackdropBlur(mouse_transparent=True).testAttribute(
        Qt.WA_TransparentForMouseEvents) is True
    assert BackdropBlur(mouse_transparent=False).testAttribute(
        Qt.WA_TransparentForMouseEvents) is False
    assert BackdropBlur().testAttribute(
        Qt.WA_TransparentForMouseEvents) is False


def test_backdrop_blur_uses_no_graphics_effect(qapp):
    from utils.widgets.backdrop_blur import BackdropBlur
    b = BackdropBlur()
    b.set_source_pixmap(QPixmap(10, 10))
    assert b.graphicsEffect() is None


def test_overlay_backdrop_alias_is_shared_class(qapp):
    from utils.widgets.customization_overlay import _BackdropBlur
    from utils.widgets.backdrop_blur import BackdropBlur
    assert _BackdropBlur is BackdropBlur
