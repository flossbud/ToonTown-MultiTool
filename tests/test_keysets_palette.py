"""Keysets palette: dark branches byte-equal today's literals; light = Vivid."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

from PySide6.QtGui import QColor

from utils.color_math import darken_rgb, lighten_rgb, with_alpha
from utils.theme_manager import get_theme_colors
from utils.widgets.keysets import palette as kp

BLUE, BLUE_B = "#4A8FE7", "#6ba8f0"
RED = "#E05252"


def test_detail_card_dark_matches_legacy():
    top, bot, border = kp.detail_card(BLUE, BLUE_B, True)
    assert top == darken_rgb(QColor(BLUE), 0.30)
    assert bot == darken_rgb(QColor(BLUE), 0.15)
    assert border == with_alpha(BLUE_B, 0.55)


def test_detail_card_light_is_vivid():
    top, bot, border = kp.detail_card(BLUE, BLUE_B, False)
    assert top == lighten_rgb(QColor(BLUE), 0.58)
    assert bot == lighten_rgb(QColor(BLUE), 0.72)
    assert border == QColor(BLUE_B)                     # solid in light
    rtop, _, _ = kp.detail_card(RED, "#ea7a7a", False)
    assert rtop == lighten_rgb(QColor(RED), 0.58)       # identity-derived


def test_rail_item_selected_same_both_themes():
    for is_dark in (True, False):
        top, bot, border = kp.rail_item(BLUE, BLUE_B, True, is_dark)
        assert top == darken_rgb(QColor(BLUE), 0.95)
        assert bot == darken_rgb(QColor(BLUE), 0.72)
        assert border == QColor(BLUE_B)


def test_rail_item_unselected_dark_legacy_light_vivid():
    top, bot, border = kp.rail_item(BLUE, BLUE_B, False, True)
    assert (top, bot) == (darken_rgb(QColor(BLUE), 0.30), darken_rgb(QColor(BLUE), 0.15))
    assert border == with_alpha(BLUE_B, 0.55)
    top, bot, border = kp.rail_item(BLUE, BLUE_B, False, False)
    assert (top, bot) == (lighten_rgb(QColor(BLUE), 0.58), lighten_rgb(QColor(BLUE), 0.72))
    assert border == with_alpha(BLUE_B, 0.55)


def test_keycap_dark_branches_match_legacy():
    assert kp.keycap("conflict", "#3399ff", False, True) == (
        QColor("#e05252"), QColor("#f28b8b"), QColor("#ffffff"))
    assert kp.keycap("movement", "#3399ff", False, True) == (
        QColor("#3399ff"), with_alpha("#ffffff", 0.55), QColor("#ffffff"))
    assert kp.keycap("aux", "#3399ff", False, True) == (
        with_alpha("#ffffff", 0.22), with_alpha("#ffffff", 0.40), QColor("#ffffff"))
    assert kp.keycap("unassigned", "#3399ff", False, True) == (
        with_alpha("#000000", 0.28), with_alpha("#ffffff", 0.08), with_alpha("#ffffff", 0.40))
    assert kp.keycap("unassigned", "#3399ff", True, True)[0] == with_alpha("#000000", 0.18)


def test_keycap_light_branches():
    assert kp.keycap("conflict", "#3399ff", False, False) == (
        QColor("#e05252"), QColor("#f28b8b"), QColor("#ffffff"))   # red family kept
    assert kp.keycap("movement", "#3399ff", False, False) == (
        QColor("#3399ff"), with_alpha("#ffffff", 0.7), QColor("#ffffff"))
    assert kp.keycap("aux", "#3399ff", False, False) == (
        QColor("#ffffff"), QColor("#475569"), QColor("#0f172a"))
    fill, border, ink = kp.keycap("unassigned", "#3399ff", False, False)
    assert fill == with_alpha("#ffffff", 0.55)
    assert border == with_alpha("#0f172a", 0.14)
    assert ink == QColor("#334155")
    assert kp.keycap("unassigned", "#3399ff", True, False)[0] == with_alpha("#ffffff", 0.70)


def test_spotlight_ring():
    assert kp.spotlight_ring(True) == with_alpha("#ffffff", 0.9)
    assert kp.spotlight_ring(False) == with_alpha("#0f172a", 0.9)


def test_inks():
    assert kp.card_ink(True) == "#ffffff" and kp.card_ink(False) == "#0f172a"
    assert kp.card_ink_soft(True) == "rgba(255,255,255,0.62)"
    assert kp.card_ink_soft(False) == "#33415f"
    assert kp.card_ink_faint(True) == "rgba(255,255,255,0.5)"
    assert kp.card_ink_faint(False) == "#33415f"


def test_field_row_active_same_both_themes():
    for is_dark in (True, False):
        bg, border = kp.field_row(True, "#3399ff", is_dark)
        assert bg == with_alpha("#3399ff", 0.12).name(QColor.HexArgb)
        assert border == with_alpha("#3399ff", 0.5).name(QColor.HexArgb)


def test_field_row_inactive():
    assert kp.field_row(False, "#3399ff", True) == ("rgba(0,0,0,0.24)", "rgba(0,0,0,0.30)")
    assert kp.field_row(False, "#3399ff", False) == (
        "rgba(255,255,255,0.45)", "rgba(15,23,42,0.14)")


def test_field_value():
    assert kp.field_value(True, True) == ("rgba(224,82,82,0.16)", "#e05252", "#ff9a9a")
    assert kp.field_value(False, True) == ("rgba(0,0,0,0.35)", "rgba(255,255,255,0.14)", "#ffffff")
    assert kp.field_value(True, False) == ("rgba(224,82,82,0.10)", "#e05252", "#b91c1c")
    assert kp.field_value(False, False) == ("#ffffff", "rgba(15,23,42,0.18)", "#0f172a")


def test_rail_and_chrome_strings():
    assert "rgba(0,0,0,0.24)" in kp.rail_panel_qss(True)
    assert "#e8ecf1" in kp.rail_panel_qss(False) and "#cbd5e1" in kp.rail_panel_qss(False)
    assert kp.rail_header_ink(True) == "rgba(255,255,255,0.5)"
    assert kp.rail_header_ink(False) == "#475569"
    # On a selected (accent-filled) item the ink stays white in BOTH themes;
    # on an unselected light (pastel) item it flips dark.
    assert kp.rail_item_ink(True, False) == "#ffffff"
    assert kp.rail_item_ink(False, True) == "#ffffff"
    assert kp.rail_item_ink(False, False) == "#0f172a"
    assert "rgba(0,0,0,0.28)" in kp.rail_chip_qss(True, True)
    assert "rgba(255,255,255,0.55)" in kp.rail_chip_qss(False, False)


def test_add_set_qss_has_no_margin():
    for is_dark in (True, False):
        qss = kp.add_set_qss(is_dark)
        assert "margin" not in qss
    assert "#aaaaaa" in kp.add_set_qss(True)
    assert "#64748b" in kp.add_set_qss(False) and "#94a3b8" in kp.add_set_qss(False)


def test_picker_and_back_button():
    assert kp.picker_card_fill(True) == QColor("#0d0f13")
    assert kp.picker_card_fill(False) == QColor("#ffffff")
    assert kp.picker_ink("title", True) == "#ffffff"
    assert kp.picker_ink("title", False) == "#0f172a"
    assert kp.picker_ink("soft", True) == "rgba(255,255,255,0.6)"
    assert kp.picker_ink("soft", False) == "#33415f"
    assert kp.picker_ink("meta", True) == "rgba(255,255,255,0.7)"
    assert kp.picker_ink("meta", False) == "#33415f"
    assert kp.picker_ink("subtitle", True) == "rgba(255,255,255,0.55)"
    assert kp.picker_ink("subtitle", False) == "#33415f"
    assert "rgba(255,255,255,0.66)" in kp.back_button_qss(True)
    assert "rgba(15,23,42,0.66)" in kp.back_button_qss(False)


def test_light_token_pins():
    c = get_theme_colors(False)
    assert c["bg_input_dark"] == "#e8ecf1"     # rail panel fill
    assert c["border_light"] == "#cbd5e1"      # rail panel border
    assert c["text_muted"] == "#475569"        # rail header / aux keycap border
    assert c["text_disabled"] == "#64748b"     # add-set label
    assert c["text_primary"] == "#0f172a"      # primary ink
