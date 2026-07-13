"""Rail panel/items/chips follow the palette; Add Set renders full height."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtWidgets import QApplication

from utils.widgets.keysets import palette as kp


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _panel(qapp, is_dark):
    from utils.widgets.keysets.set_list import SetListPanel
    p = SetListPanel(is_dark=is_dark)
    p.set_data(game_short="ttr", game_accent="#4A8FE7",
               sets=[{"forward": "w"}, {"forward": "i"}],
               set_names=["Default", "Alt"], selected_index=0)
    return p


def test_panel_qss_follows_theme(qapp):
    assert "rgba(0,0,0,0.24)" in _panel(qapp, True).styleSheet()
    light = _panel(qapp, False)
    assert "#e8ecf1" in light.styleSheet()
    assert "#475569" in light._header_label.styleSheet()


def test_item_ink_selected_vs_unselected_light(qapp):
    light = _panel(qapp, False)
    sel, unsel = light._items[0], light._items[1]
    assert "#ffffff" in sel._name_lbl.styleSheet()      # accent body keeps white
    assert "#0f172a" in unsel._name_lbl.styleSheet()    # pastel body flips dark
    # chips follow the same rule
    assert "rgba(0,0,0,0.28)" in sel._chips[0].styleSheet()
    assert "rgba(255,255,255,0.55)" in unsel._chips[0].styleSheet()


def test_item_ink_restyles_on_selection_change(qapp):
    light = _panel(qapp, False)
    light._items[1].set_selected(True)
    assert "#ffffff" in light._items[1]._name_lbl.styleSheet()


def test_add_set_full_height_and_no_margin(qapp):
    for is_dark in (True, False):
        p = _panel(qapp, is_dark)
        # The palette QSS itself stays margin-free (root-cause invariant;
        # also pinned directly in tests/test_keysets_palette.py). The 9px
        # gap margin is applied only at the call site, now that the fixed
        # height has room for it without squishing the capsule.
        assert "margin" not in kp.add_set_qss(is_dark)
        assert "margin-top: 9px" in p._add_btn.styleSheet()
        # Fixed height = 41: 9px gap zone + 32px capsule (see implementation).
        assert p._add_btn.height() == 41 or p._add_btn.sizeHint().height() == 41


def test_apply_theme_restyles_panel(qapp):
    p = _panel(qapp, True)
    p.apply_theme(False)
    assert "#e8ecf1" in p.styleSheet()
    assert "#0f172a" in p._items[1]._name_lbl.styleSheet()
