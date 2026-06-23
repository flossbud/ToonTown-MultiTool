import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")
os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")

from PySide6.QtGui import QColor
from utils.card_dim import dim_color, lerp_color
from tabs.multitoon._tab import SetSelectorWidget


def _prime(s):
    s._bg = "#4A8FE7"
    s._text_color = "#ffffff"
    s._border_color = "#6AAFFF"


def test_resolved_colors_progress0_and_1(qapp):
    s = SetSelectorWidget(None)
    _prime(s)
    s.set_dim_progress(0.0)
    bg, text, border = s._resolved_colors()
    assert bg == QColor("#4A8FE7") and border == QColor("#6AAFFF") and text == QColor("#ffffff")
    s.set_dim_progress(1.0)
    bg, text, border = s._resolved_colors()
    assert bg == dim_color(QColor("#4A8FE7"))
    assert border == dim_color(QColor("#6AAFFF"))
    assert text == dim_color(QColor("#ffffff"))


def test_resolved_colors_mid(qapp):
    s = SetSelectorWidget(None)
    _prime(s)
    s.set_dim_progress(0.5)
    bg, _, _ = s._resolved_colors()
    assert bg == lerp_color(QColor("#4A8FE7"), dim_color(QColor("#4A8FE7")), 0.5)


def test_set_dim_progress_guard_no_op(qapp):
    s = SetSelectorWidget(None)
    assert s._dim_progress == 0.0
    s.set_dim_progress(1.0)
    assert s._dim_progress == 1.0
    calls = []
    s.update = lambda *a, **k: calls.append(1)
    s.set_dim_progress(1.0)            # same value -> no repaint
    assert calls == []


def test_set_dimmed_wrapper(qapp):
    s = SetSelectorWidget(None)
    s.set_dimmed(True)
    assert s._dim_progress == 1.0
    s.set_dimmed(False)
    assert s._dim_progress == 0.0
