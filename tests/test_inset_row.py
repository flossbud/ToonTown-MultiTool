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


def test_label_indent_uniform_regardless_of_control_width(app):
    """The helper's 470px cap must not center the text column: label x must
    be identical for narrow (switch-sized) and wide (segment-sized) controls."""
    from PySide6.QtWidgets import QWidget as _W
    rows = []
    for ctrl_w in (50, 300):
        row = InsetRow("Label", helper="Some helper text.")
        ctrl = _W()
        ctrl.setFixedSize(ctrl_w, 30)
        row.set_control(ctrl)
        row.resize(660, 60)
        row.show()
        rows.append(row)
    QApplication.processEvents()
    xs = [r.label_widget.mapTo(r, r.label_widget.rect().topLeft()).x()
          for r in rows]
    assert xs[0] == xs[1]
    for r in rows:
        r.hide()


def test_bottom_buttons_right_aligned(app):
    row = InsetRow("External CC log directory (advanced)", helper="h")
    a, b = QPushButton("Browse"), QPushButton("Clear")
    row.add_control(a)
    row.add_control(b)
    slot = row._bottom_control_slot
    # stretch first, then the buttons in add order -> right-aligned row
    assert slot.itemAt(0).spacerItem() is not None
    assert slot.itemAt(1).widget() is a
    assert slot.itemAt(2).widget() is b


def test_long_helper_grows_row_instead_of_clipping(app):
    """Wrapped helper text must grow the row (heightForWidth), never clip -
    regression for the 2026-07 alignment experiment that froze row heights."""
    short = InsetRow("Label", helper="One line.")
    long_ = InsetRow("Label", helper=(
        "Disabled by default. Both games' Terms of Service prohibit "
        "automation tools. Your previous per-toon Keep-Alive selections "
        "are preserved across restarts and upgrades."))
    for r in (short, long_):
        r.setFixedWidth(660)
        r.show()
    QApplication.processEvents()
    assert long_.sizeHint().height() > short.sizeHint().height()
    assert long_.helper_widget.heightForWidth(400) > \
        long_.helper_widget.heightForWidth(600)
    for r in (short, long_):
        r.hide()
