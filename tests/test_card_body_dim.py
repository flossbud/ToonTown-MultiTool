import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")
os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")

from PySide6.QtGui import QColor
from utils.card_dim import dim_color, lerp_color
from utils.color_math import darken_rgb
from tabs.multitoon._compact_layout import _QuadCardBackground, _PortraitFrame


def test_body_lit_progress0_unchanged(qapp):
    w = _QuadCardBackground("br")
    w.configure(QColor(255, 0, 0))
    w.set_dim_progress(0.0)
    top, bot, border = w._resolved_colors()
    assert border == QColor(255, 0, 0)
    assert top == darken_rgb(QColor(255, 0, 0), 0.28)
    assert bot == darken_rgb(QColor(255, 0, 0), 0.14)


def test_body_dim_progress1_matches_dim_color(qapp):
    w = _QuadCardBackground("br")
    w.configure(QColor(255, 0, 0))
    w.set_dim_progress(1.0)
    top, bot, border = w._resolved_colors()
    base = dim_color(QColor(255, 0, 0))
    assert border == base
    assert top == darken_rgb(base, 0.28)
    assert bot == darken_rgb(base, 0.14)


def test_body_mid_progress_lerps(qapp):
    w = _QuadCardBackground("br")
    w.configure(QColor(255, 0, 0))
    w.set_dim_progress(0.5)
    top, bot, border = w._resolved_colors()
    assert border == lerp_color(QColor(255, 0, 0), dim_color(QColor(255, 0, 0)), 0.5)
    # the gradient path runs darken_rgb over the intermediate lerped base
    mid_base = lerp_color(QColor(255, 0, 0), dim_color(QColor(255, 0, 0)), 0.5)
    assert top == darken_rgb(mid_base, 0.28)
    assert bot == darken_rgb(mid_base, 0.14)


def test_body_override_uses_body_not_accent(qapp):
    w = _QuadCardBackground("br")
    w.configure(QColor(255, 0, 0), body=QColor(0, 0, 255))
    w.set_dim_progress(1.0)
    top, bot, border = w._resolved_colors()
    body_dim = dim_color(QColor(0, 0, 255))
    assert top == darken_rgb(body_dim, 0.28)
    assert bot == darken_rgb(body_dim, 0.14)
    assert border == dim_color(QColor(255, 0, 0))


def test_set_dimmed_wrapper(qapp):
    w = _QuadCardBackground("br")
    w.set_dimmed(True)
    assert w._dim_progress == 1.0
    w.set_dimmed(False)
    assert w._dim_progress == 0.0


def test_portrait_ring_progress(qapp):
    f = _PortraitFrame()
    f.configure(QColor(0, 200, 0))
    f.set_dim_progress(0.0)
    assert f._resolved_ring() == QColor(0, 200, 0)
    f.set_dim_progress(1.0)
    assert f._resolved_ring() == dim_color(QColor(0, 200, 0))
    f.set_dim_progress(0.5)
    assert f._resolved_ring() == lerp_color(QColor(0, 200, 0), dim_color(QColor(0, 200, 0)), 0.5)
