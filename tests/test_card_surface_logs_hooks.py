import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QWidget


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def test_add_row_stretch_is_forwarded(qapp):
    from utils.widgets.card_surface import CardSurface
    card = CardSurface("purple", "Logs")
    filler, pane = QWidget(), QWidget()
    card.add_row(filler)
    card.add_row(pane, stretch=1)
    lay = card._body_layout
    assert lay.stretch(lay.indexOf(filler)) == 0
    assert lay.stretch(lay.indexOf(pane)) == 1


def test_set_sub_widget_adds_to_text_column(qapp):
    from utils.widgets.card_surface import CardSurface
    card = CardSurface("purple", "Logs")
    status = QLabel("status")
    card.set_sub_widget(status)
    assert card._text_col.indexOf(status) >= 0
    # A pre-existing sub label would sit above the custom widget; with none
    # set, the slot is just the custom widget.
    assert card.sub_label is None


def test_gap_kwarg_sets_both_layout_spacings(qapp):
    from utils.widgets.card_surface import CardSurface
    card = CardSurface("purple", "Logs", gap=11)
    assert card.layout().spacing() == 11
    assert card._body_layout.spacing() == 11


def test_default_gap_unchanged_for_existing_consumers(qapp):
    from utils.widgets.card_surface import CardSurface
    card = CardSurface("teal", "Diagnostics")
    assert card.layout().spacing() == 12
    assert card._body_layout.spacing() == 12
