"""Keycaps follow the palette per theme."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from utils.color_math import with_alpha


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _board(qapp, is_dark):
    from utils.widgets.keysets.visual_keyboard import VisualKeyboard
    return VisualKeyboard(is_dark=is_dark)


def _cap(kb, code):
    return kb._caps[code]


def test_unassigned_cap_light_vs_dark(qapp):
    for is_dark, fill in ((True, with_alpha("#000000", 0.28)),
                          (False, with_alpha("#ffffff", 0.55))):
        kb = _board(qapp, is_dark)
        cap = _cap(kb, "q")
        assert cap.state == "unassigned"
        assert cap._colors()[0] == fill


def test_apply_theme_retints_live(qapp):
    kb = _board(qapp, True)
    cap = _cap(kb, "q")
    assert cap._colors()[0] == with_alpha("#000000", 0.28)
    kb.apply_theme(False)
    assert cap._colors()[0] == with_alpha("#ffffff", 0.55)
