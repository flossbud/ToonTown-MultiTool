import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")
os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")

from PySide6.QtGui import QColor
from utils.card_dim import dim_color
from tabs.multitoon._tab import _ka_fill_border, KA_ORANGE, KA_ORANGE_BORDER


def test_ka_lit():
    fill, border = _ka_fill_border(is_rf=False, dimmed=False)
    assert fill == KA_ORANGE and border == KA_ORANGE_BORDER


def test_ka_dimmed():
    fill, border = _ka_fill_border(is_rf=False, dimmed=True)
    assert fill == dim_color(QColor(KA_ORANGE)).name()
    assert border == dim_color(QColor(KA_ORANGE_BORDER)).name()


def test_ka_rapidfire_lit():
    fill, border = _ka_fill_border(is_rf=True, dimmed=False)
    assert fill == "#E05252" and border == "#ef8d8d"


def test_ka_rapidfire_dimmed():
    fill, border = _ka_fill_border(is_rf=True, dimmed=True)
    assert fill == dim_color(QColor("#E05252")).name()
    assert border == dim_color(QColor("#ef8d8d")).name()
