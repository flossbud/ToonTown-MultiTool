"""SplitEditor surfaces follow the palette per theme."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")
os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from utils.color_math import lighten_rgb, darken_rgb, with_alpha


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _editor(qapp, is_dark):
    from utils.widgets.keysets.split_editor import SplitEditor
    return SplitEditor(keymap_manager=None, is_dark=is_dark)


def _forward_row(ed):
    # SplitEditor exposes its FieldRows through the action-keyed ``_rows`` dict,
    # which is populated by ``_build_rows`` (normally driven by ``set_game`` ->
    # keymap_manager). With ``keymap_manager=None`` we cannot call ``set_game``,
    # so we seed ``_actions`` and build the rows directly - ``_build_rows`` never
    # dereferences the manager. ``_move_rows`` is a QVBoxLayout, not a dict.
    ed._actions = ["forward"]
    ed._build_rows()
    return ed._rows["forward"]


def test_detail_card_colors_follow_theme(qapp):
    from utils.widgets.keysets.split_editor import _DetailCard
    card = _DetailCard()
    card.set_accent("#4A8FE7", "#6ba8f0")
    card.set_theme(False)
    top, bot, border = card._colors()
    assert top == lighten_rgb(QColor("#4A8FE7"), 0.58)
    assert bot == lighten_rgb(QColor("#4A8FE7"), 0.72)
    assert border == QColor("#6ba8f0")
    card.set_theme(True)
    top, bot, border = card._colors()
    assert top == darken_rgb(QColor("#4A8FE7"), 0.30)
    assert border == with_alpha("#6ba8f0", 0.55)


def test_editor_inks_follow_theme(qapp):
    ed = _editor(qapp, False)
    assert "#0f172a" in ed._title.styleSheet()
    assert "#33415f" in ed._sub.styleSheet()
    assert "#33415f" in ed._helper.styleSheet()
    assert "#b91c1c" in ed._conflict_banner.styleSheet()
    ed.apply_theme(True)
    assert "#ffffff" in ed._title.styleSheet()
    assert "rgba(255,255,255,0.62)" in ed._sub.styleSheet()
    assert "#ff9a9a" in ed._conflict_banner.styleSheet()


def test_field_row_and_value_follow_theme(qapp):
    ed = _editor(qapp, False)
    row = _forward_row(ed)
    assert "rgba(255,255,255,0.45)" in row.styleSheet()
    row.set_field("w", conflict=False, mac=False, locked=False)
    assert "#0f172a" in row._field.styleSheet()
    row.set_field("w", conflict=True, mac=False, locked=False)
    assert "#b91c1c" in row._field.styleSheet()
    ed.apply_theme(True)
    assert "rgba(0,0,0,0.24)" in row.styleSheet()
    row.set_field("w", conflict=False, mac=False, locked=False)
    assert "#ffffff" in row._field.styleSheet()
