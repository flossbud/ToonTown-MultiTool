"""InsetRow - translucent v2 setting row with animated disabled treatment."""
import pytest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from utils.widgets.inset_row import InsetRow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_single_control_goes_top_right(app):
    row = InsetRow("Appearance")
    ctl = QLabel("x")
    row.set_control(ctl)
    assert row.control_widget is ctl
    assert row._top_control_slot.indexOf(ctl) >= 0


def test_two_controls_migrate_to_bottom_row(app):
    row = InsetRow("External CC log directory (advanced)", helper="h")
    a, b = QPushButton("Browse"), QPushButton("Clear")
    row.add_control(a)
    row.add_control(b)
    assert not row._bottom_row.isHidden()
    assert row._bottom_control_slot.indexOf(a) >= 0
    assert row._bottom_control_slot.indexOf(b) >= 0


def test_full_width_control(app):
    row = InsetRow("Interval")
    w = QLabel("segment")
    row.set_full_width_control(w)
    assert row.control_widget is w
    assert not row._bottom_row.isHidden()


def test_disabled_blocks_input_and_restores(app):
    row = InsetRow("Action")
    ctl = QPushButton("x")
    row.set_control(ctl)
    row.apply_theme(is_dark=True)
    row.set_row_disabled(True)
    assert not row.isEnabled()
    row.set_row_disabled(False)
    assert row.isEnabled()


def test_helper_present_and_themed(app):
    row = InsetRow("Reduce motion", helper="System default follows your desktop.")
    row.apply_theme(is_dark=False)
    assert row.helper_widget is not None
    assert "11px" in row.helper_widget.styleSheet()
