"""V2 design tokens (Settings/Launch v2 kit) - accent pairs + theme token sets."""
from utils.theme_manager import V2_ACCENTS, get_v2_tokens


def test_accent_pairs_match_handoff():
    assert V2_ACCENTS["blue"] == {"c": "#0077ff", "b": "#3399ff"}
    assert V2_ACCENTS["teal"] == {"c": "#1fb8a6", "b": "#4dd2c3"}
    assert set(V2_ACCENTS) == {
        "blue", "yellow", "ttr", "cc", "orange", "pink", "green", "teal", "red",
        "purple",
    }


def test_dark_tokens():
    t = get_v2_tokens(is_dark=True)
    assert t["row_bg"] == "rgba(0, 0, 0, 61)"          # rgba(0,0,0,0.24)
    assert t["row_border"] == "rgba(0, 0, 0, 77)"      # 0.30
    assert t["label"] == "#ffffff"
    assert t["ctrl_bg"] == "rgba(0, 0, 0, 89)"         # 0.35
    assert t["btn_border"] == "rgba(255, 255, 255, 46)"  # 0.18


def test_light_tokens_differ():
    t = get_v2_tokens(is_dark=False)
    assert t["label"] == "#0f172a"
    assert t["row_bg"] == "rgba(255, 255, 255, 158)"   # 0.62
    assert t["nav_idle_text"] == "#475569"


def test_radii_constants():
    t = get_v2_tokens(is_dark=True)
    assert t["radius_row"] == 13 and t["radius_card"] == 20
