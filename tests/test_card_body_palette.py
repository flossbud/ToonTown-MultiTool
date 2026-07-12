"""Palette injection into the card body + portrait ring painters."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")
os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")

from PySide6.QtGui import QColor

from utils.card_palette import card_palette
from utils.theme_manager import get_theme_colors
from tabs.multitoon._compact_layout import _QuadCardBackground, _PortraitFrame

TTR = QColor("#4A8FE7")


def _light_pal():
    return card_palette(TTR, None, get_theme_colors(False), False)


def _dark_pal():
    return card_palette(TTR, None, get_theme_colors(True), True)


def test_body_light_lit_is_vivid(qapp):
    w = _QuadCardBackground("br")
    w.configure(TTR, palette=_light_pal())
    w.set_dim_progress(0.0)
    top, bot, border = w._resolved_colors()
    p = _light_pal()
    assert (top, bot, border) == (p.body_top_lit, p.body_bot_lit, p.border_lit)


def test_body_light_off_is_paper(qapp):
    w = _QuadCardBackground("br")
    w.configure(TTR, palette=_light_pal())
    w.set_dim_progress(1.0)
    top, bot, border = w._resolved_colors()
    p = _light_pal()
    assert (top, bot, border) == (p.body_top_off, p.body_bot_off, p.border_off)


def test_body_dark_palette_matches_legacy_no_palette_path(qapp):
    lit = _QuadCardBackground("br"); lit.configure(TTR)                      # legacy
    pal = _QuadCardBackground("br"); pal.configure(TTR, palette=_dark_pal()) # injected
    for t in (0.0, 1.0):
        lit.set_dim_progress(t); pal.set_dim_progress(t)
        assert lit._resolved_colors() == pal._resolved_colors()


def test_ring_light_endpoints(qapp):
    f = _PortraitFrame()
    f.configure(TTR, palette=_light_pal())
    f.set_dim_progress(0.0)
    assert f._resolved_ring() == _light_pal().border_lit
    f.set_dim_progress(1.0)
    assert f._resolved_ring() == _light_pal().border_off


def test_ring_dark_palette_matches_legacy(qapp):
    a = _PortraitFrame(); a.configure(TTR)
    b = _PortraitFrame(); b.configure(TTR, palette=_dark_pal())
    for t in (0.0, 0.5, 1.0):
        a.set_dim_progress(t); b.set_dim_progress(t)
        assert a._resolved_ring() == b._resolved_ring()
