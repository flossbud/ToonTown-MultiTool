"""v2 pill controls - button, segment, dropdown, chord, expander."""
import pytest
from PySide6.QtWidgets import QApplication

from utils.widgets.pill_controls import (
    ChordPill, DropdownPill, GhostExpander, PillButton, SegmentedPill,
)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_pill_button_neutral_and_danger(app):
    b = PillButton("Browse")
    b.apply_theme(is_dark=True)
    assert b.height() == 30
    d = PillButton("Clear", tone="danger")
    d.apply_theme(is_dark=True)
    assert "#e05252" in d.styleSheet()


def test_segmented_pill_click_emits_and_set_silent(app):
    seg = SegmentedPill(["System", "Light", "Dark"])
    seg.apply_theme(is_dark=True, accent_key="blue")
    fired = []
    seg.index_changed.connect(fired.append)
    seg.setCurrentIndex(2)                # silent by contract
    assert seg.currentIndex() == 2 and fired == []
    seg.resize(seg.sizeHint())
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    ev = QMouseEvent(QMouseEvent.Type.MouseButtonPress,
                     QPointF(5, 15), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    seg.mousePressEvent(ev)
    assert seg.currentIndex() == 0 and fired == [0]


def test_segmented_pill_stretch_expands(app):
    from PySide6.QtWidgets import QSizePolicy
    seg = SegmentedPill(["A", "B"], stretch=True)
    assert seg.sizePolicy().horizontalPolicy() == QSizePolicy.Expanding


def test_dropdown_pill_is_settings_combo(app):
    from utils.shared_widgets import SettingsComboBox
    d = DropdownPill()
    assert isinstance(d, SettingsComboBox)
    d.addItems(["(none)", "Acct"])
    d.apply_theme(is_dark=True)
    assert d.height() == 30


def test_chord_pill_bound_vs_unbound_styling(app):
    c = ChordPill(None, lambda t: None)
    c.apply_theme(is_dark=True)
    unbound_ss = c.styleSheet()
    c.set_chord("ctrl+alt+r")
    assert c.styleSheet() != unbound_ss


def test_ghost_expander_text(app):
    g = GhostExpander()
    g.set_state(expanded=False, more_count=13)
    assert g.text() == "Show 13 more..."
    g.set_state(expanded=True, more_count=13)
    assert g.text() == "Show less"


def test_segmented_pill_disabled_paints_muted(app):
    seg = SegmentedPill(["A", "B"])
    seg.apply_theme(is_dark=True, accent_key="orange")
    seg.resize(seg.sizeHint())
    enabled_img = seg.grab().toImage()
    seg.setEnabled(False)
    disabled_img = seg.grab().toImage()
    assert enabled_img != disabled_img
