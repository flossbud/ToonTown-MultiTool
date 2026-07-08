from utils.widgets.keysets import game_meta as gm
from utils.theme_manager import V2_ACCENTS

def test_only_ttr_and_cc_ship():
    assert set(gm.GAME_META) == {"ttr", "cc"}

def test_game_meta_fields():
    ttr = gm.GAME_META["ttr"]
    assert ttr.title == "Toontown Rewritten" and ttr.short == "TTR"
    assert ttr.accent_c == "#4A8FE7" and ttr.accent_b == "#6ba8f0"
    assert ttr.banner_asset == "ttr-banner.png"
    cc = gm.GAME_META["cc"]
    assert cc.short == "CC" and cc.accent_c == "#F26D21" and cc.banner_asset == "cc-banner.png"

def test_set_accent_cycles_v2_subset():
    assert gm.set_accent(0) == (V2_ACCENTS["blue"]["c"], V2_ACCENTS["blue"]["b"])
    assert gm.set_accent(1) == (V2_ACCENTS["red"]["c"], V2_ACCENTS["red"]["b"])
    assert gm.set_accent(7) == gm.set_accent(0)
    assert gm.set_accent(2) == (V2_ACCENTS["yellow"]["c"], V2_ACCENTS["yellow"]["b"])
