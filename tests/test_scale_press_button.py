# tests/test_scale_press_button.py
import sys
import pytest
from PySide6.QtWidgets import QApplication
import utils.motion as motion
from utils.widgets.scale_press import ScalePushButton


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication(sys.argv)


def test_press_shrinks_and_release_restores(qt_app, monkeypatch):
    # Reduced motion -> the scale is applied instantly, so the end state is
    # deterministic without pumping the event loop.
    monkeypatch.setattr(motion, "is_reduced", lambda: True)
    b = ScalePushButton()
    assert b.paint_scale == 1.0
    b.pressed.emit()
    assert b.paint_scale == pytest.approx(ScalePushButton.PRESS_SCALE)
    b.released.emit()
    assert b.paint_scale == pytest.approx(1.0)


def test_press_is_a_shrink(qt_app):
    assert 0.0 < ScalePushButton.PRESS_SCALE < 1.0


def test_press_does_not_change_geometry(qt_app, monkeypatch):
    monkeypatch.setattr(motion, "is_reduced", lambda: True)
    b = ScalePushButton()
    b.setFixedSize(32, 32)
    b.show()
    qt_app.processEvents()
    before = b.size()
    b.pressed.emit()
    assert b.size() == before          # paint-only: layout/geometry unchanged
    b.released.emit()


def test_paint_scale_property_animates_value(qt_app):
    # With motion enabled the property is animatable (QPropertyAnimation target).
    b = ScalePushButton()
    b._set_paint_scale(0.5)
    assert b.paint_scale == pytest.approx(0.5)
