"""Grandstand palette: dark branch is the handoff §9 token set, verbatim."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

from PySide6.QtGui import QColor

from utils.color_math import with_alpha
from utils.widgets.grandstand import palette as gp


def test_game_card_active_ttr_dark():
    d = gp.game_card("ttr", True, True)
    assert d["bg"] == QColor("#14283d")
    assert d["border"] == QColor("#4A8FE7")          # --game-ttr
    assert d["art_opacity"] == 0.72
    assert d["saturation"] == 1.0


def test_game_card_inactive_is_desaturated_and_dim():
    d = gp.game_card("cc", False, True)
    assert d["art_opacity"] == 0.34
    assert d["saturation"] == 0.45


def test_game_card_active_cc_uses_cc_identity():
    d = gp.game_card("cc", True, True)
    assert d["bg"] == QColor("#3a1e0e")
    assert d["border"] == QColor("#F26D21")          # --game-cc


def test_hero_base_per_game():
    assert gp.hero_base("ttr") == QColor("#1d4a7a")
    assert gp.hero_base("cc") == QColor("#7a3a12")


def test_hero_scrim_darkens_left_to_right():
    stops = gp.hero_scrim("ttr")
    assert [p for p, _ in stops] == [0.0, 0.56, 1.0]
    assert stops[0][1].alphaF() > stops[-1][1].alphaF()   # copy side is darkest


def test_cc_scrim_is_warm_not_the_arts_blue_teal():
    """Handoff §4.1b: the CC skyline is natively blue-teal; without a warm
    scrim the largest element on screen contradicts CC's orange."""
    r, g, b, _ = gp.hero_scrim("cc")[0][1].getRgb()
    assert r > b


def test_play_button_enabled_is_v2_yellow():
    d = gp.play_button(True, True)
    assert d["bg"] == QColor("#d4a017")              # --v2-yellow
    assert d["border"] == QColor("#e8c14d")          # --v2-yellow-b
    assert d["ink"] == QColor("#231a04")


def test_play_button_disabled_has_no_shadow():
    d = gp.play_button(False, True)
    assert d["bg"] == with_alpha("#ffffff", 0.12)
    assert d["shadow"] is None


def test_panel_dark_tokens():
    d = gp.panel(True)
    assert d["bg"] == QColor("#252525")              # --bg-card
    assert d["border"] == QColor("#363636")          # --border-card


def test_card_surface_selected_border_is_blue():
    d = gp.card_surface("#4a8fe7", True, True)
    assert d["border"] == QColor("#3399ff")          # --blue-border


def test_card_surface_top_is_accent_tinted():
    """Handoff §4.1d: linear-gradient(accent 26%, rgba(0,0,0,.3))."""
    d = gp.card_surface("#e74a4a", False, True)
    assert d["top"] == with_alpha("#e74a4a", 0.26)
    assert d["bot"] == with_alpha("#000000", 0.30)


def test_card_ink_selected_footer_is_blue_tinted():
    assert gp.card_ink(True, True)["foot"] == QColor("#9fc9f5")
    assert gp.card_ink(False, True)["foot"] == QColor("#888888")   # --text-muted


def test_status_ink_running_is_green():
    d = gp.status_ink("running", True)
    assert d["text"] == QColor("#56d66a")            # --green-border
    assert d["dot"] == QColor("#56c856")             # --status-dot-active


def test_status_ink_failed_is_error_red():
    assert gp.status_ink("failed", True)["text"] == QColor("#ff7575")


def test_head_link_gold_and_disabled():
    assert gp.head_link(True, True, True) == QColor("#e8c14d")
    assert gp.head_link(False, False, True) == QColor("#666666")   # --text-disabled


def test_every_function_accepts_both_themes():
    """The light branch is unimplemented, but no signature may reject it."""
    for fn, args in (
        (gp.game_card, ("ttr", True)), (gp.play_button, (True,)),
        (gp.panel, ()), (gp.card_ink, (False,)),
        (gp.control_chip, (False,)), (gp.status_ink, ("idle",)),
        (gp.advisory_strip, ()),
    ):
        for is_dark in (True, False):
            assert fn(*args, is_dark) is not None
