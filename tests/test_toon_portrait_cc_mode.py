"""Tests for the CC paint mode on ToonPortraitWidget."""

import pytest
from PySide6.QtGui import QColor


@pytest.fixture
def qt_app():
    from PySide6.QtWidgets import QApplication
    import sys
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


def test_cc_mode_off_by_default(qt_app):
    from tabs.multitoon._tab import ToonPortraitWidget
    w = ToonPortraitWidget(1)
    # Constructor-default: not in CC mode
    assert getattr(w, "_cc_mode", False) is False


def test_set_cc_mode_with_values_enables_mode(qt_app):
    from tabs.multitoon._tab import ToonPortraitWidget
    w = ToonPortraitWidget(1)
    w.set_cc_mode(
        skin_rgb=(0.0, 0.4, 0.65),
        accent_rgb=(0.0, 0.4, 0.65),
        gloves_rgb=(1.0, 1.0, 1.0),
        emoji="🐶",
    )
    assert w._cc_mode is True
    assert w._cc_emoji == "🐶"
    assert isinstance(w._cc_skin, QColor)
    assert w._cc_skin.redF() == pytest.approx(0.0)


def test_set_cc_mode_with_none_clears_mode(qt_app):
    from tabs.multitoon._tab import ToonPortraitWidget
    w = ToonPortraitWidget(1)
    w.set_cc_mode(
        skin_rgb=(0.0, 0.4, 0.65),
        accent_rgb=(0.0, 0.4, 0.65),
        gloves_rgb=(1.0, 1.0, 1.0),
        emoji="🐶",
    )
    w.set_cc_mode(skin_rgb=None, accent_rgb=None, gloves_rgb=None, emoji=None)
    assert w._cc_mode is False


def test_set_cc_mode_paint_does_not_raise(qt_app):
    from PySide6.QtGui import QPixmap
    from tabs.multitoon._tab import ToonPortraitWidget
    w = ToonPortraitWidget(1)
    w.resize(80, 80)
    w.set_cc_mode(
        skin_rgb=(0.0, 0.4, 0.65),
        accent_rgb=(0.0, 0.4, 0.65),
        gloves_rgb=(1.0, 1.0, 1.0),
        emoji="🐶",
    )
    pix = QPixmap(w.size())
    w.render(pix)  # should not raise
