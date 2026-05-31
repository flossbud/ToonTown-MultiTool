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
    assert s.TRAFFIC["min"] == ("#febc2e", "#7a4e00")
    assert s.TRAFFIC["max"] == ("#28c840", "#0c5a1e")
    assert s.TRAFFIC["close"] == ("#ff5f56", "#7a1410")


def test_glyph_pixel_size_scales_and_floors():
    assert s.glyph_pixel_size(16) == 11
    assert s.glyph_pixel_size(16) > 9
    assert s.glyph_pixel_size(10) == 9


def test_is_dark_bg_by_luminance():
    assert s.is_dark_bg("#1a1a1a") is True
    assert s.is_dark_bg("#f8fafc") is False


def test_is_dark_bg_rejects_malformed_hex():
    import pytest
    for bad in ("#abc", "black", "#12345", "##123456", "#zzzzzz"):
        with pytest.raises(ValueError):
            s.is_dark_bg(bad)


def test_window_edge_colors_theme_aware():
    dark = s.window_edge_colors("#1a1a1a")
    light = s.window_edge_colors("#f8fafc")
    assert dark["outline"] == "rgba(255,255,255,0.14)"
    assert dark["rim"] == "rgba(255,255,255,0.10)"
    assert light["outline"] == "rgba(15,23,42,0.16)"
    assert light["rim"] == "rgba(255,255,255,0.55)"


def test_card_qss_uniform_outline_when_radius_and_outline():
    qss = s.card_qss("app_card", "#1a1a1a", 16, "rgba(255,255,255,0.14)")
    assert "QWidget#app_card" in qss
    assert "border-radius: 16px" in qss
    assert "border: 1px solid rgba(255,255,255,0.14)" in qss
    assert "border-top:" not in qss
    assert "border-bottom:" not in qss


def test_card_qss_plain_when_radius_zero_and_no_colors():
    qss = s.card_qss("app_card", "#1a1a1a", 0, None)
    assert "QWidget#app_card" in qss
    assert "background: #1a1a1a" in qss
    assert "border-radius" not in qss
    assert "border-top:" not in qss


def test_card_qss_plain_unless_both_radius_and_outline():
    q1 = s.card_qss("app_card", "#1a1a1a", 16, None)
    assert "border" not in q1 and "border-radius" not in q1
    q2 = s.card_qss("app_card", "#1a1a1a", 0, "rgba(255,255,255,0.14)")
    assert "border" not in q2 and "border-radius" not in q2


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


def test_header_top_radius_includes_rim_when_given():
    qss = s.header_top_radius_qss("#1a1a1a", "#333", 16, top_rim="rgba(255,255,255,0.10)")
    assert "border-top: 1px solid rgba(255,255,255,0.10)" in qss
    assert "border-bottom: 1px solid #333" in qss
    assert "border-top-left-radius: 15px" in qss


def test_header_top_radius_no_rim_by_default():
    qss = s.header_top_radius_qss("#1a1a1a", "#333", 16)
    assert "border-top:" not in qss
