import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")
os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")

from PySide6.QtGui import QColor
from utils.card_dim import dim_color
from utils.color_math import darken_rgb
from tabs.multitoon._compact_layout import _QuadCardBackground, _PortraitFrame


def test_body_lit_colors_unchanged(qapp):
    w = _QuadCardBackground("br")
    w.configure(QColor(255, 0, 0), dimmed=False)
    top, bot, border = w._resolved_colors()
    assert border == QColor(255, 0, 0)
    assert top == darken_rgb(QColor(255, 0, 0), 0.28)
    assert bot == darken_rgb(QColor(255, 0, 0), 0.14)


def test_body_dimmed_colors_use_dim_color_once(qapp):
    w = _QuadCardBackground("br")
    w.configure(QColor(255, 0, 0), dimmed=True)
    top, bot, border = w._resolved_colors()
    base = dim_color(QColor(255, 0, 0))
    assert border == base
    assert top == darken_rgb(base, 0.28)
    assert bot == darken_rgb(base, 0.14)


def test_body_override_dimmed_uses_body_not_accent(qapp):
    # body and accent are independent inputs: the gradient derives from `body`,
    # the border always tracks `accent`.
    w = _QuadCardBackground("br")
    w.configure(QColor(255, 0, 0), dimmed=True, body=QColor(0, 0, 255))
    top, bot, border = w._resolved_colors()
    body_dimmed = dim_color(QColor(0, 0, 255))
    assert top == darken_rgb(body_dimmed, 0.28)
    assert bot == darken_rgb(body_dimmed, 0.14)
    assert border == dim_color(QColor(255, 0, 0))


def test_portrait_ring_dim(qapp):
    f = _PortraitFrame()
    f.configure(QColor(0, 200, 0), dimmed=False)
    assert f._resolved_ring() == QColor(0, 200, 0)
    f.configure(QColor(0, 200, 0), dimmed=True)
    assert f._resolved_ring() == dim_color(QColor(0, 200, 0))
