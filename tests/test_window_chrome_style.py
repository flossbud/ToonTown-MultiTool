# tests/test_window_chrome_style.py
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

from utils.widgets import window_chrome_style as s


def test_radius_and_inset_constants():
    assert s.RADIUS_NORMAL == 16
    assert s.RADIUS_MAXIMIZED == 0
    assert s.BOTTOM_INSET == 16
    assert s.STROKE_INSET == 1
    assert s.DOT_DIAMETER == 16


def test_traffic_colors_are_amber_green_red():
    assert s.TRAFFIC["min"][0] == "#febc2e"
    assert s.TRAFFIC["max"][0] == "#28c840"
    assert s.TRAFFIC["close"][0] == "#ff5f56"
    for _key, (_dot, glyph) in s.TRAFFIC.items():
        assert glyph != "#ffffff"


def test_glyph_pixel_size_scales_and_floors():
    assert s.glyph_pixel_size(16) == 11
    assert s.glyph_pixel_size(16) > 9
    assert s.glyph_pixel_size(10) == 9


def test_is_dark_bg_by_luminance():
    assert s.is_dark_bg("#1a1a1a") is True
    assert s.is_dark_bg("#f8fafc") is False


def test_is_dark_bg_rejects_malformed_hex():
    import pytest
    for bad in ("#abc", "black", "#12345"):
        with pytest.raises(ValueError):
            s.is_dark_bg(bad)


def test_bevel_border_colors_theme_aware():
    dark = s.bevel_border_colors("#1a1a1a")
    light = s.bevel_border_colors("#f8fafc")
    assert "255,255,255" in dark["top"] and "0.16" in dark["top"]
    assert "255,255,255" in dark["side"] and "0.10" in dark["side"]
    assert "255,255,255" in dark["bottom"] and "0.05" in dark["bottom"]
    assert "0,0,0" in light["top"] and "0.06" in light["top"]
    assert "0,0,0" in light["side"] and "0.12" in light["side"]
    assert "0,0,0" in light["bottom"] and "0.18" in light["bottom"]


def test_card_qss_contains_radius_and_four_border_colors():
    colors = s.bevel_border_colors("#1a1a1a")
    qss = s.card_qss("app_card", "#1a1a1a", 16, colors)
    assert "QWidget#app_card" in qss
    assert "border-radius: 16px" in qss
    assert f"border-top: 1px solid {colors['top']}" in qss
    assert f"border-bottom: 1px solid {colors['bottom']}" in qss
    assert f"border-left: 1px solid {colors['side']}" in qss
    assert f"border-right: 1px solid {colors['side']}" in qss


def test_card_qss_plain_when_radius_zero_and_no_colors():
    qss = s.card_qss("app_card", "#1a1a1a", 0, None)
    assert "QWidget#app_card" in qss
    assert "background: #1a1a1a" in qss
    assert "border-radius" not in qss
    assert "border-top:" not in qss


def test_header_top_radius_nests_inside_stroke():
    qss = s.header_top_radius_qss("#1a1a1a", "#333", 16)
    assert "background: #1a1a1a" in qss
    assert "border-top-left-radius: 15px" in qss
    assert "border-top-right-radius: 15px" in qss
    assert "border-bottom: 1px solid #333" in qss


def test_header_top_radius_zero_when_maximized():
    qss = s.header_top_radius_qss("#1a1a1a", "#333", 0)
    assert "border-top-left-radius: 0px" in qss
    assert "border-top-right-radius: 0px" in qss
