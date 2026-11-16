"""Grandstand palette: dark branch is the handoff §9 token set, verbatim."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

from PySide6.QtGui import QColor

from utils.color_math import with_alpha
from utils.widgets.grandstand import palette as gp


def test_game_accent_is_the_identity_hex():
    assert gp.game_accent("ttr").upper() == "#4A8FE7"    # --game-ttr
    assert gp.game_accent("cc").upper() == "#F26D21"     # --game-cc


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
    assert gp.hero_base("ttr", True) == QColor("#1d4a7a")
    assert gp.hero_base("cc", True) == QColor("#7a3a12")


def test_hero_scrim_darkens_left_to_right():
    stops = gp.hero_scrim("ttr", True)
    assert [p for p, _ in stops] == [0.0, 0.56, 1.0]
    assert stops[0][1].alphaF() > stops[-1][1].alphaF()   # copy side is darkest


def test_cc_scrim_is_warm_not_the_arts_blue_teal():
    """Handoff §4.1b: the CC skyline is natively blue-teal; without a warm
    scrim the largest element on screen contradicts CC's orange."""
    r, g, b, _ = gp.hero_scrim("cc", True)[0][1].getRgb()
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


def test_hero_ink_is_scrim_facing_white():
    d = gp.hero_ink(True)
    assert d["greeting"] == QColor("#ffffff")
    assert d["names"] == with_alpha("#ffffff", 0.82)


def test_lineup_ink_is_scrim_facing_and_theme_independent():
    expected = {
        "cameo_disc": with_alpha("#000000", 0.30),
        "placeholder_border": with_alpha("#ffffff", 0.40),
        "placeholder_ink": with_alpha("#ffffff", 0.67),
    }
    assert gp.lineup_ink(True) == expected
    assert gp.lineup_ink(False) == expected


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


def test_card_star_is_gold_only_when_starred():
    assert gp.card_star(True, True)["ink"] == QColor("#e8c14d")   # --v2-yellow-b
    assert gp.card_star(False, True)["ink"] == QColor("#888888")  # --text-muted


def test_status_ink_running_is_green():
    d = gp.status_ink("running", True)
    assert d["text"] == QColor("#56d66a")            # --green-border
    assert d["dot"] == QColor("#56c856")             # --status-dot-active


def test_status_ink_failed_is_error_red():
    assert gp.status_ink("failed", True)["text"] == QColor("#ff7575")


def test_card_action_fills_match_the_tile_they_port_from():
    assert gp.card_action("running", "#4a8fe7", True)["bg"] == QColor("#e05252")
    assert gp.card_action("queued", "#4a8fe7", True)["bg"] == QColor("#e05252")
    assert gp.card_action("need_2fa", "#4a8fe7", True)["bg"] == QColor("#a763d8")
    assert gp.card_action("failed", "#4a8fe7", True)["bg"] == QColor("#c84e34")


def test_card_action_idle_takes_the_accounts_accent():
    assert gp.card_action("idle", "#e74a4a", True)["bg"] == QColor("#e74a4a")


def test_head_link_gold_and_disabled():
    assert gp.head_link(True, True, True) == QColor("#e8c14d")
    assert gp.head_link(False, False, True) == QColor("#666666")   # --text-disabled


def test_shelf_head_ink_dark_tokens():
    d = gp.shelf_head_ink(True)
    assert d["title"] == QColor("#bbbbbb")          # --text-secondary
    assert d["sub"] == QColor("#888888")            # --text-muted


def test_add_tile_border_is_border_light():
    assert gp.add_tile(True)["border"] == QColor("#555555")      # --border-light


def test_shelf_fade_dissolves_the_panel_background():
    d = gp.shelf_scroll(True)
    assert d["fade_in"] == gp.panel(True)["bg"]
    assert d["fade_out"].alpha() == 0
    assert d["fade_out"].rgb() == d["fade_in"].rgb()
    assert d["thumb"] == QColor("#555555")              # --border-light


def test_selected_ribbon_uses_blue_tokens():
    d = gp.ribbon(True, True)
    assert d["bg"] == QColor("#0077ff")              # --blue
    assert d["border"] == QColor("#3399ff")          # --blue-border


def test_unselected_ribbon_has_dark_translucent_backing():
    assert gp.ribbon(False, True)["bg"] == with_alpha("#000000", 0.35)


def test_hero_ghost_button_has_dark_translucent_backing():
    assert gp.hero_ghost_button(True)["bg"] == with_alpha("#000000", 0.26)


def _luminance(c: QColor) -> float:
    def lin(v):
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(c.red()) + 0.7152 * lin(c.green()) + 0.0722 * lin(c.blue())


def _contrast(a: QColor, b: QColor) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


ROSTER_THEMED = (
    (gp.panel, ()), (gp.card_surface, ("#4a8fe7", False)),
    (gp.card_surface, ("#4a8fe7", True)), (gp.card_ink, (False,)),
    (gp.card_ink, (True,)), (gp.control_chip, (False,)),
    (gp.control_chip, (True,)), (gp.card_star, (False,)),
    (gp.card_star, (True,)), (gp.card_placeholder, ()),
    (gp.status_ink, ("idle",)), (gp.status_ink, ("running",)),
    (gp.head_link, (True, False)), (gp.head_link, (True, True)),
    (gp.head_link, (False, False)), (gp.shelf_head_ink, ()),
    (gp.add_tile, ()), (gp.ribbon, (False,)), (gp.advisory_strip, ()),
    (gp.game_card, ("ttr", False)), (gp.game_card, ("cc", False)),
)


def test_every_roster_token_has_a_light_branch_of_its_own():
    """The roster shipped dark-only: on the light app its panel, cards and
    inks were the dark ones. A light branch that returns the dark value is
    the same bug, so each must differ."""
    for fn, args in ROSTER_THEMED:
        assert fn(*args, True) != fn(*args, False), (fn.__name__, args)


def test_light_roster_text_is_readable_on_the_light_panel():
    """AA for the text a user has to read on a white panel. The dark hues
    (grey #888, green #56d66a, gold #e8c14d) measure 2.2 to 3.5 on white."""
    white = gp.panel(False)["bg"]
    inks = {
        "card name": gp.card_ink(False, False)["name"],
        "card user": gp.card_ink(False, False)["user"],
        "head title": gp.shelf_head_ink(False)["title"],
        "link": gp.head_link(True, False, False),
        "gold link": gp.head_link(True, True, False),
        "add tile": gp.add_tile(False)["ink"],
        "chip": gp.control_chip(False, False)["ink"],
        "inactive game": gp.game_card("ttr", False, False)["name_ink"],
    }
    for state in ("idle", "running", "failed", "need_2fa", "queued",
                  "logging_in", "launching", "loading"):
        inks[f"status {state}"] = gp.status_ink(state, False)["text"]
    for name, ink in inks.items():
        assert _contrast(ink, white) >= 4.5, (name, ink.name(),
                                              round(_contrast(ink, white), 2))


def test_active_game_card_meta_reads_on_the_game_art():
    """It was --text-muted grey on the TTR blue. It sits on game art in both
    themes, so it is a white alpha and does not follow the app theme."""
    for game in ("ttr", "cc"):
        dark, light = (gp.game_card(game, True, t) for t in (True, False))
        assert dark == light
        assert dark["meta_ink"].red() == 255 and dark["meta_ink"].alphaF() >= 0.7


def test_disabled_control_chip_drops_to_the_disabled_ink():
    assert gp.control_chip(False, True, False)["ink"] == QColor("#666666")
    assert gp.control_chip(False, True, False) != gp.control_chip(False, True, True)
    assert gp.control_chip(False, False, False) != gp.control_chip(False, False, True)


def test_every_function_accepts_both_themes():
    """No signature may reject either theme."""
    for fn, args in (
        (gp.game_card, ("ttr", True)), (gp.hero_base, ("ttr",)),
        (gp.hero_scrim, ("ttr",)), (gp.play_button, (True,)),
        (gp.panel, ()), (gp.card_surface, ("#4a8fe7", False)),
        (gp.card_ink, (False,)),
        (gp.control_chip, (False,)), (gp.status_ink, ("idle",)),
        (gp.card_action, ("idle", "#4a8fe7")),
        (gp.head_link, (True, False)), (gp.advisory_strip, ()),
        (gp.shelf_head_ink, ()), (gp.add_tile, ()), (gp.shelf_scroll, ()),
        (gp.ribbon, (False,)), (gp.lineup_ink, ()),
        (gp.hero_ghost_button, ()),
    ):
        for is_dark in (True, False):
            assert fn(*args, is_dark) is not None
