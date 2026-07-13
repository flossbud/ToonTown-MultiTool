"""Game picker + back button follow the palette."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from utils.widgets.keysets import palette as kp


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_picker_card_fill_tokens():
    assert kp.picker_card_fill(True) == QColor("#0d0f13")
    assert kp.picker_card_fill(False) == QColor("#ffffff")


def test_picker_labels_follow_theme_and_restyle(qapp):
    from utils.widgets.keysets.game_picker import GamePickerView

    v = GamePickerView(True)                 # dark
    v.set_games([("ttr", 2), ("cc", 1)])
    card = v._cards["ttr"]

    # Dark: every promoted ink site is white / white-alpha.
    assert "#ffffff" in v._title.styleSheet()
    assert "#ffffff" in card._title_lbl.styleSheet()

    # apply_theme must restyle the view labels AND every card's labels.
    v.apply_theme(False)
    assert "#0f172a" in v._title.styleSheet()          # title ink flips dark
    assert "#33415f" in v._subtitle.styleSheet()       # subtitle ink flips
    assert "#0f172a" in card._title_lbl.styleSheet()   # card title flips
    assert "#33415f" in card._sub_lbl.styleSheet()     # card soft ink flips
    assert "#33415f" in card._edit_lbl.styleSheet()    # card meta ink flips


def test_back_button_branches():
    assert "rgba(15,23,42,0.66)" in kp.back_button_qss(False)
    assert "rgba(255,255,255,0.66)" in kp.back_button_qss(True)
