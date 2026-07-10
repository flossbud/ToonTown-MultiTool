import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def _has_ink(icon, size):
    img = icon.pixmap(size, size).toImage().convertToFormat(QImage.Format_ARGB32)
    return any(img.pixelColor(x, y).alpha() > 0
               for x in range(size) for y in range(size))


def test_new_glyphs_render_ink(qapp):
    from utils.icon_factory import (make_arrow_down_icon, make_copy_icon,
                                    make_pause_icon)
    for maker, size in ((make_copy_icon, 11), (make_pause_icon, 11),
                        (make_arrow_down_icon, 10)):
        assert _has_ink(maker(size, QColor("#ffffff")), size), maker.__name__


def test_reused_glyphs_render_ink(qapp):
    from utils.icon_factory import make_nav_terminal, make_play_icon
    assert _has_ink(make_play_icon(11, QColor("#ffffff")), 11)
    assert _has_ink(make_nav_terminal(20, QColor("#ffffff")), 20)
