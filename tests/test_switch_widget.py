"""Tests for the Switch widget — the accent-blue pill replacing IOSToggle in Settings."""

import os
import sys

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication


# Make the project root importable when tests are invoked from anywhere.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


def _click(widget):
    """Synthesize a left-click at the widget's center."""
    from PySide6.QtCore import QPointF, QPoint, QEvent
    center = QPoint(widget.width() // 2, widget.height() // 2)
    press = QMouseEvent(
        QEvent.MouseButtonPress, QPointF(center),
        widget.mapToGlobal(center).toPointF() if hasattr(widget.mapToGlobal(center), "toPointF") else QPointF(widget.mapToGlobal(center)),
        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
    )
    widget.mousePressEvent(press)


def test_switch_initial_state_off(qapp):
    from utils.shared_widgets import Switch
    s = Switch(checked=False)
    assert s.isChecked() is False


def test_switch_initial_state_on(qapp):
    from utils.shared_widgets import Switch
    s = Switch(checked=True)
    assert s.isChecked() is True


def test_switch_set_checked_updates_state(qapp):
    from utils.shared_widgets import Switch
    s = Switch(checked=False)
    s.setChecked(True)
    assert s.isChecked() is True
    s.setChecked(False)
    assert s.isChecked() is False


def test_switch_click_toggles_and_emits(qapp):
    from utils.shared_widgets import Switch
    s = Switch(checked=False)
    s.show()
    received = []
    s.toggled.connect(received.append)
    _click(s)
    assert s.isChecked() is True
    assert received == [True]
    _click(s)
    assert s.isChecked() is False
    assert received == [True, False]


def test_switch_setchecked_does_not_emit_when_unchanged(qapp):
    """Calling setChecked with the current value should not re-emit toggled."""
    from utils.shared_widgets import Switch
    s = Switch(checked=False)
    received = []
    s.toggled.connect(received.append)
    s.setChecked(False)
    assert received == []


def test_switch_reduced_motion_snaps_thumb(qapp, monkeypatch):
    """When motion is reduced, the thumb animation should snap to its target."""
    import utils.motion as motion
    monkeypatch.setattr(motion, "is_reduced", lambda: True)
    from utils.shared_widgets import Switch
    s = Switch(checked=False)
    s.setChecked(True)
    # When reduced, the animation does not run; the thumb x must already match
    # the on-position (TRACK_W - THUMB_D - PADDING).
    expected = s.TRACK_W - s.THUMB_D - s.PADDING
    assert s._thumb_x == pytest.approx(expected, abs=0.5)


def test_switch_set_theme_colors_applies_palette(qapp):
    """The Switch must accept theme colors so refresh_theme can re-tint it."""
    from utils.shared_widgets import Switch
    s = Switch(checked=True)
    # Should not raise.
    s.set_theme_colors(
        track_on="#0077ff",
        track_off="#3a3a3a",
        thumb="#ffffff",
    )
    # Internal state stored so paint can use it.
    assert s._track_on == "#0077ff"
    assert s._track_off == "#3a3a3a"
    assert s._thumb_color == "#ffffff"
