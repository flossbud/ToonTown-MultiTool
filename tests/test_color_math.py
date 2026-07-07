"""Unit tests for utils.color_math."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from utils.color_math import darken_hsl


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _channels_close(a: QColor, b: QColor, tol: int = 2) -> bool:
    return (
        abs(a.red() - b.red()) <= tol
        and abs(a.green() - b.green()) <= tol
        and abs(a.blue() - b.blue()) <= tol
    )


def test_darken_hsl_saturated_red(qapp):
    """A saturated mid-tone red should darken to a noticeably darker but
    still saturated red. Hue (0°) preserved."""
    out = darken_hsl(QColor("#e74a4a"), 0.7)
    # Reference from brainstorming: ~#b91e1e (within rounding tolerance).
    assert _channels_close(out, QColor("#b91e1e"), tol=5)


def test_darken_hsl_pure_black_clamps(qapp):
    """Pure black has lightness 0; the result must also be black (no
    underflow or hue glitch)."""
    out = darken_hsl(QColor("#000000"), 0.7)
    assert out.red() == 0 and out.green() == 0 and out.blue() == 0


def test_darken_hsl_pure_white(qapp):
    """Pure white at L=1.0 darkens cleanly. Reference: ~#b3b3b3."""
    out = darken_hsl(QColor("#ffffff"), 0.7)
    assert _channels_close(out, QColor("#b3b3b3"), tol=5)


def test_darken_hsl_achromatic_gray(qapp):
    """Achromatic input (saturation 0) must stay neutral gray after darken
    -- no hue artifact from Qt's hue=-1 sentinel."""
    out = darken_hsl(QColor("#808080"), 0.7)
    assert abs(out.red() - out.green()) <= 1
    assert abs(out.green() - out.blue()) <= 1
    assert out.red() < 0x80


def test_darken_hsl_preserves_alpha(qapp):
    """Alpha must pass through unchanged."""
    c = QColor("#4a8fe7")
    c.setAlpha(128)
    out = darken_hsl(c, 0.7)
    assert out.alpha() == 128


def test_rgb_floats_to_hex():
    from utils.color_math import rgb_floats_to_hex
    assert rgb_floats_to_hex((1.0, 0.0, 0.0)) == "#ff0000"
    assert rgb_floats_to_hex(None) is None
    assert rgb_floats_to_hex((0.0, 0.4, 0.65)) == "#0066a6"
