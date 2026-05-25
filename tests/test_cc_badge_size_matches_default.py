"""Regression: the CC paint path must draw a circle of the same diameter
as the default (non-CC) paint path.

`ToonPortraitWidget.paintEvent` non-CC branch uses `r = min(cx, cy) - 2.0`,
inscribing the circle 2 px from each edge of the widget rect. The CC
branch delegates to `paint_cc_badge`, which previously drew on the full
rect (`drawEllipse(rect)`). The 2 px discrepancy was visible as the
circle "growing" the moment CC data populated. This test pins the CC
bg circle to the same 2 px inset.
"""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _top_y_of_first_opaque(img: QImage, x: int) -> int:
    for y in range(img.height()):
        if img.pixelColor(x, y).alpha() > 0:
            return y
    return -1


def test_paint_cc_badge_bg_circle_matches_non_cc_diameter(qapp):
    """The CC bg ellipse must be inset 2 px from the rect edge, matching
    the non-CC paint path. At a 60x60 rect, the topmost opaque pixel of
    the center column should be at y=2 (not y=0)."""
    from utils.cc_badge_paint import paint_cc_badge

    img = QImage(60, 60, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    paint_cc_badge(p, QRect(0, 0, 60, 60), QColor(200, 100, 100), None, 1)
    p.end()

    top = _top_y_of_first_opaque(img, 30)
    assert top == 2, (
        f"CC bg circle top at y={top}; expected y=2 to match the non-CC "
        f"paint path's 2 px inset (r = min(cx, cy) - 2.0)"
    )
