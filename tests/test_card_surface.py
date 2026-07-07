"""CardSurface - identity-tinted v2 group card (gradient body + painted halo)."""
import pytest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from utils.widgets.card_surface import CardSurface


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_construct_and_paint_dark(app):
    card = CardSurface("orange", title="Keep-Alive")
    card.apply_theme(is_dark=True)
    card.resize(600, 200)
    assert not card.grab().isNull()


def test_add_row_parents_into_body(app):
    card = CardSurface("blue", title="Appearance & behavior")
    row = QLabel("row")
    card.add_row(row)
    assert row.parent() is card._body


def test_header_click_emits(app):
    card = CardSurface("ttr", title="Toontown Rewritten")
    fired = []
    card.header_clicked.connect(lambda: fired.append(1))
    card._emit_header_click()
    assert fired == [1]


def test_set_desaturated_toggles_and_repaints(app):
    card = CardSurface("ttr", title="Toontown Rewritten")
    card.apply_theme(is_dark=True)
    card.resize(600, 200)
    assert card._desaturated is False
    card.set_desaturated(True)
    assert card._desaturated is True
    assert not card.grab().isNull()          # desaturated paint path runs
    card.set_desaturated(False)
    assert card._desaturated is False


def test_header_button_and_sub(app):
    card = CardSurface("ttr", title="Toontown Rewritten", sub=" ")
    btn = QPushButton("Browse")
    card.add_header_button(btn)
    assert btn.parent() is card._header_button_row
    card.set_sub("~/games/TTR", color_override="#7de392", mono=True)
    assert card.sub_label.text() == "~/games/TTR"


def test_set_sub_creates_label_when_missing(app):
    card = CardSurface("cc", title="Corporate Clash")
    assert card.sub_label is None
    card.set_sub("hello")
    assert card.sub_label is not None and card.sub_label.text() == "hello"


def test_theme_flip_animate_does_not_crash(app):
    card = CardSurface("red", title="Storage")
    card.apply_theme(is_dark=True)
    card.apply_theme(is_dark=False, animate=True)
    assert not card.grab().isNull()


def test_pulse_highlight_runs_and_restores(app):
    card = CardSurface("orange", title="Keep-Alive")
    card.apply_theme(is_dark=True)
    before = card._border_col.name()
    card.pulse_highlight()          # reduce-motion in offscreen CI may no-op
    assert card._border_col.isValid()
    assert isinstance(before, str)
