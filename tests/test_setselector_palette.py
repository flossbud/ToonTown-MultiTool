"""Keyset selector off endpoints (paper) with legacy default."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")
os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from utils.card_dim import dim_color, lerp_color


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _selector(qapp):
    from tabs.multitoon._tab import SetSelectorWidget
    return SetSelectorWidget(keymap_manager=None)


def test_off_colors_none_is_legacy(qapp):
    w = _selector(qapp)
    w.set_dim_progress(1.0)
    bg, text, border = w._resolved_colors()
    assert bg == dim_color(QColor(w._bg))


def test_off_colors_injected_endpoints(qapp):
    w = _selector(qapp)
    w.set_off_colors(bg=QColor("#e8ecf1"), text=QColor("#475569"),
                     border=QColor("#cbd5e1"), label=QColor("#475569"))
    w.set_dim_progress(1.0)
    bg, text, border = w._resolved_colors()
    assert (bg, text, border) == (QColor("#e8ecf1"), QColor("#475569"), QColor("#cbd5e1"))
    w.set_dim_progress(0.5)
    bg, _, _ = w._resolved_colors()
    assert bg == lerp_color(QColor(w._bg), QColor("#e8ecf1"), 0.5)


def test_label_color_follows_injection(qapp):
    w = _selector(qapp)
    w.set_off_colors(bg=QColor("#e8ecf1"), text=QColor("#475569"),
                     border=QColor("#cbd5e1"), label=QColor("#475569"))
    w.set_dim_progress(1.0)
    assert w._resolved_label_color() == QColor("#475569")


def test_label_color_legacy_is_dimmed_white(qapp):
    w = _selector(qapp)
    w.set_dim_progress(1.0)
    white = QColor("#ffffff")
    assert w._resolved_label_color() == dim_color(white)
