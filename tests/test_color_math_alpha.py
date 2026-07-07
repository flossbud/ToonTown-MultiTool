"""alpha()/with_alpha() - QSS + QColor alpha helpers (Settings v2 kit)."""
from PySide6.QtGui import QColor

from utils.color_math import alpha, with_alpha


def test_alpha_returns_qss_rgba_string():
    assert alpha("#0077ff", 0.55) == "rgba(0, 119, 255, 140)"


def test_alpha_accepts_qcolor():
    assert alpha(QColor("#ff9500"), 0.20) == "rgba(255, 149, 0, 51)"


def test_alpha_clamps_fraction():
    assert alpha("#ffffff", 2.0) == "rgba(255, 255, 255, 255)"
    assert alpha("#ffffff", -1.0) == "rgba(255, 255, 255, 0)"


def test_with_alpha_returns_qcolor_preserving_rgb():
    c = with_alpha("#3399ff", 0.33)
    assert isinstance(c, QColor)
    assert (c.red(), c.green(), c.blue()) == (0x33, 0x99, 0xff)
    assert c.alpha() == round(0.33 * 255)
