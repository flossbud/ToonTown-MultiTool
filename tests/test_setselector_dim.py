import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")
os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")

from PySide6.QtGui import QColor
from utils.card_dim import dim_color
from tabs.multitoon._tab import SetSelectorWidget


def test_resolved_colors_lit_and_dimmed(qapp):
    s = SetSelectorWidget(None)
    s._bg = "#4A8FE7"
    s._text_color = "#ffffff"
    s._border_color = "#6AAFFF"
    bg, text, border = s._resolved_colors()
    assert bg == QColor("#4A8FE7")
    assert text == QColor("#ffffff")
    assert border == QColor("#6AAFFF")
    s.set_dimmed(True)
    bg, text, border = s._resolved_colors()
    assert bg == dim_color(QColor("#4A8FE7"))
    assert border == dim_color(QColor("#6AAFFF"))
    assert text == dim_color(QColor("#ffffff"))


def test_set_dimmed_guard(qapp):
    s = SetSelectorWidget(None)
    assert s._dimmed is False
    s.set_dimmed(True)
    assert s._dimmed is True
    # Calling again with the same value is a no-op: no repaint scheduled.
    calls = []
    s.update = lambda *a, **k: calls.append(1)
    s.set_dimmed(True)
    assert calls == []
    assert s._dimmed is True
