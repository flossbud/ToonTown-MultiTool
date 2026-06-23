import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")
os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")

from PySide6.QtGui import QColor
from utils.card_dim import dim_color, lerp_color
from tabs.multitoon._tab import _ka_fill_border, KA_ORANGE, KA_ORANGE_BORDER


def test_ka_progress0_lit():
    fill, border = _ka_fill_border(is_rf=False, progress=0.0)
    assert fill == KA_ORANGE and border == KA_ORANGE_BORDER


def test_ka_progress1_dim():
    fill, border = _ka_fill_border(is_rf=False, progress=1.0)
    assert fill == dim_color(QColor(KA_ORANGE)).name()
    assert border == dim_color(QColor(KA_ORANGE_BORDER)).name()


def test_ka_mid_lerps():
    fill, _ = _ka_fill_border(is_rf=False, progress=0.5)
    assert fill == lerp_color(QColor(KA_ORANGE), dim_color(QColor(KA_ORANGE)), 0.5).name()


def test_ka_rapidfire_progress0_lit():
    fill, border = _ka_fill_border(is_rf=True, progress=0.0)
    assert fill == QColor("#E05252").name() and border == QColor("#ef8d8d").name()


def test_ka_rapidfire_progress1():
    fill, border = _ka_fill_border(is_rf=True, progress=1.0)
    assert fill == dim_color(QColor("#E05252")).name()
    assert border == dim_color(QColor("#ef8d8d")).name()
