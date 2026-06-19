"""Tests for CardMetrics pure value object.

Run in isolation:
    TTMT_NO_VENV_REEXEC=1 QT_QPA_PLATFORM=offscreen ./venv/bin/python -m pytest tests/test_card_metrics.py -q
"""
import pytest

from utils.overlay.card_metrics import CardMetrics


def test_base_metrics_at_scale_1():
    m = CardMetrics(scale=1.0)
    assert m.portrait == 172 and m.card_radius == 20 and m.cutout_r == 96
    assert m.emblem == 156 and m.grid_gap == 18
    assert m.card_border == 5 and m.card_pad == 18 and m.card_min_h == 232
    assert m.ctrl_w == 158 and m.portrait_ring == 4


def test_metrics_scale_proportionally():
    m = CardMetrics(scale=0.5)
    assert m.portrait == 86 and m.cutout_r == 48 and m.emblem == 78
    assert m.font_pt(14) == 7.0 and isinstance(m.font_pt(14), float)


def test_immutable():
    m = CardMetrics(scale=1.0)
    with pytest.raises(AttributeError):
        m.portrait = 999


def test_repr():
    assert repr(CardMetrics(scale=1.0)) == "CardMetrics(scale=1.0)"


def test_scale_clamped():
    assert CardMetrics(scale=9.0).scale == 1.75


def test_scale_clamped_low():
    assert CardMetrics(scale=0.1).scale == 0.5


def test_icon_px_banker_rounding():
    # 17 * 0.5 = 8.5; Python's round() uses banker's rounding -> round to even -> 8
    m = CardMetrics(scale=0.5)
    assert m.icon_px(17) == 8
    # 16 * 0.5 = 8.0 -> rounds to 8 (exact)
    assert m.icon_px(16) == 8
    # icon_px must return an int
    assert isinstance(m.icon_px(17), int)
