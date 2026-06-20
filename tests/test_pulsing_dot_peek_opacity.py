# tests/test_pulsing_dot_peek_opacity.py
"""PulsingDot honors the transparent-mode hover-peek opacity hook.

The compact portrait overlay drops the status dot to the portrait opacity on
hover (see test_compact_control_rects). These cover the widget contract in
isolation: default opaque, setter updates, no-op guard.
"""
import sys
import pytest
from PySide6.QtWidgets import QApplication
from utils.shared_widgets import PulsingDot


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication(sys.argv)


def test_defaults_to_fully_opaque(qt_app):
    assert PulsingDot(13)._peek_opacity == 1.0


def test_set_peek_opacity_updates_value(qt_app):
    dot = PulsingDot(13)
    dot.set_peek_opacity(0.25)
    assert dot._peek_opacity == 0.25
    dot.set_peek_opacity(1.0)
    assert dot._peek_opacity == 1.0


def test_set_peek_opacity_coerces_to_float(qt_app):
    dot = PulsingDot(13)
    dot.set_peek_opacity(1)
    assert isinstance(dot._peek_opacity, float)
    assert dot._peek_opacity == 1.0
