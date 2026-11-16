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


def test_every_function_accepts_both_themes():
    """The light branch is unimplemented, but no signature may reject it."""
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


# ── Appearance editor (sub-project B; handoff §4.2, §4.3, §4.6, §9) ─────────

_APPEARANCE = (
    (gp.portrait_fallback, ()), (gp.appearance_stage, ()),
    (gp.appearance_group_ink, ()), (gp.appearance_chip, (False, False)),
    (gp.appearance_chip, (True, False)), (gp.appearance_chip, (False, True)),
    (gp.appearance_disabled, ()), (gp.color_well, ("rest",)),
    (gp.color_well, ("hover",)), (gp.color_well, ("open",)),
    (gp.gradient_bar_border, ()), (gp.well_popover, ()),
    (gp.swap_button, (False,)), (gp.swap_button, (True,)),
    (gp.look_swatch, (False,)), (gp.look_swatch, (True,)),
    (gp.pose_tile, (False, False)), (gp.pose_tile, (True, False)),
    (gp.pose_tile, (False, True)), (gp.pose_fade, ()), (gp.standin, ()),
    (gp.subject_pill, (False,)), (gp.subject_pill, (True,)),
    (gp.switcher_popover, ()), (gp.mini_link, (False, False)),
    (gp.mini_link, (True, False)), (gp.mini_link, (False, True)),
)


def _colours(value):
    if isinstance(value, QColor):
        return [value]
    if isinstance(value, dict):
        return [v for v in value.values() if isinstance(v, QColor)]
    return [v for v in value if isinstance(v, QColor)]


def test_every_appearance_surface_has_a_dark_and_a_light_branch():
    """Not merely "accepts both themes": the light theme must not be handed
    the dark values, or the editor is a dark slab in a light app."""
    for fn, args in _APPEARANCE:
        dark, light = fn(*args, True), fn(*args, False)
        assert _colours(dark) and _colours(light)
        assert dark != light, fn.__name__


def test_appearance_dark_tokens_are_the_handoffs():
    stage = gp.appearance_stage(True)
    assert stage["bg"] == QColor("#2e2e2e")              # --bg-card-inner
    assert stage["border"] == QColor("#363636")          # --border-card
    assert stage["fill"] == QColor("#0077ff")            # --blue
    chip = gp.appearance_chip(True, False, True)
    assert chip["bg"] == with_alpha("#3399ff", 0.16)
    assert chip["border"] == QColor("#3399ff")           # --blue-border
    assert chip["ink"] == QColor("#cfe6ff")
    assert gp.appearance_chip(False, False, True)["ink"] == QColor("#888888")
    assert gp.well_popover(True)["bg"] == QColor("#171a24")
    assert gp.switcher_popover(True)["bg"] == QColor("#191b22")
    assert gp.switcher_popover(True)["warn"] == QColor("#e8c14d")   # --v2-yellow-b
    assert gp.switcher_popover(True)["row_current"] == with_alpha("#0077ff", 0.16)
    assert gp.color_well("open", True)["border"] == QColor("#ffffff")
    assert gp.color_well("rest", True)["border"] == with_alpha("#ffffff", 0.18)
    assert gp.pose_tile(True, False, True)["glow"] == with_alpha("#3399ff", 0.28)
    assert gp.mini_link(True, False, True) == QColor("#e8c14d")
    assert gp.subject_pill(False, True)["bg"] == QColor("#2e2e2e")


def test_light_inks_are_the_light_theme_tokens():
    from utils.theme_manager import get_theme_colors
    light = get_theme_colors(False)
    assert gp.appearance_stage(False)["bg"].name() == light["bg_card_inner"]
    assert gp.appearance_group_ink(False)["label"].name() == light["text_muted"]
    assert gp.appearance_group_ink(False)["note"].name() == light["text_disabled"]
    assert gp.subject_pill(False, False)["ink"].name() == light["text_primary"]
    assert gp.switcher_popover(False)["bg"].name() == light["bg_card"]
    assert gp.standin(False)["title"].name() == light["text_primary"]


def _over(top: QColor, base: QColor) -> QColor:
    """`top` alpha-blended over an opaque `base`."""
    a = top.alphaF()
    return QColor(round(top.red() * a + base.red() * (1 - a)),
                  round(top.green() * a + base.green() * (1 - a)),
                  round(top.blue() * a + base.blue() * (1 - a)))


def _luminance(c: QColor) -> float:
    def channel(v):
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return (0.2126 * channel(c.red()) + 0.7152 * channel(c.green())
            + 0.0722 * channel(c.blue()))


def _contrast(ink: QColor, surface: QColor) -> float:
    hi, lo = sorted((_luminance(ink), _luminance(surface)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _light_text_pairs():
    """(what, ink, the opaque surface it is drawn on) for every piece of
    text the appearance editor shows in the light theme."""
    sheet = gp.sheet_surface(False)["bg"]
    stage = gp.appearance_stage(False)
    group = gp.appearance_group_ink(False)
    pop = gp.switcher_popover(False)
    stand = gp.standin(False)
    pill = gp.subject_pill(False, False)
    chip_on = gp.appearance_chip(True, False, False)
    yield "stage hint", stage["hint"], stage["bg"]
    yield "slider value", stage["value"], stage["bg"]
    yield "species tag", stage["tag_ink"], _over(stage["tag_bg"], stage["bg"])
    for key in ("label", "note", "readout", "body", "scope"):
        yield f"group {key}", group[key], sheet
    yield "chip", gp.appearance_chip(False, False, False)["ink"], sheet
    yield "chip hover", gp.appearance_chip(False, True, False)["ink"], sheet
    yield "chip selected", chip_on["ink"], _over(chip_on["bg"], sheet)
    yield "surprise me", gp.mini_link(True, False, False), sheet
    yield "reset all", gp.mini_link(False, False, False), sheet
    yield "look label", gp.look_swatch(False, False)["ink"], sheet
    yield "look label selected", gp.look_swatch(True, False)["ink"], sheet
    yield "pose label", gp.pose_tile(False, False, False)["ink"], sheet
    yield "pose label selected", gp.pose_tile(True, False, False)["ink"], sheet
    yield "pill name", pill["ink"], pill["bg"]
    for key in ("heading", "name", "meta", "note", "warn"):
        yield f"switcher {key}", pop[key], pop["bg"]
    yield "switcher name on the current row", pop["name"], _over(pop["row_current"], pop["bg"])
    yield "switcher meta on the current row", pop["meta"], _over(pop["row_current"], pop["bg"])
    yield "portrait art title", stand["title"], stand["bg"]
    yield "portrait art body", stand["body"], stand["bg"]
    yield "use game accent", gp.well_popover(False)["clear_ink"], gp.well_popover(False)["bg"]


def test_light_theme_text_is_readable_on_its_surface():
    """WCAG AA for normal text. The dark branch is the handoff's tokens
    verbatim and is not held to this; the light branch is ours to get right."""
    failures = [(what, ink.name(), surface.name(), round(_contrast(ink, surface), 2))
                for what, ink, surface in _light_text_pairs()
                if _contrast(ink, surface) < 4.5]
    assert failures == []


def test_the_selected_look_ring_is_visible_on_its_own_surface():
    """A white ring on the light sheet would be no ring at all."""
    for is_dark in (True, False):
        d = gp.look_swatch(True, is_dark)
        assert d["ring"] != d["gap"]
        assert d["gap"] == gp.sheet_surface(is_dark)["bg"]
