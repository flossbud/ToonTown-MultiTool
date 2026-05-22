"""Tests for paint_cc_badge: silhouette + bg paint, slot-number fallback,
and pencil rect math."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from utils import cc_badge_paint


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _paint_to_image(size: int, paint_call) -> QImage:
    pm = QPixmap(size, size)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    paint_call(p, QRect(0, 0, size, size))
    p.end()
    return pm.toImage()


def test_paints_complement_bg_when_silhouette_present(qapp):
    skin = QColor(214, 49, 49)  # vivid red

    def call(p, rect):
        cc_badge_paint.paint_cc_badge(
            p, rect, skin, asset_stem="dog", slot_number=1
        )

    img = _paint_to_image(96, call)
    # Sample inside the circle but well outside the silhouette mass.
    # At 96x96, the circle is radius ~48 centered at (48,48). The silhouette
    # sits in the inset (10%) inner rect (~10,10 to ~86,86) but the head
    # PNG is concentrated near the center. Pixel (12, 48) is firmly inside
    # the circle (distance from center ~36 < 48) and to the left of where
    # any silhouette mass lives.
    px = img.pixelColor(12, 48)
    assert px.alpha() > 200, "expected opaque bg pixel"
    # Bg is the pastel cyan-ish complement of red: red should be the weakest
    # channel (both green and blue beat it).
    assert px.red() < px.green() and px.red() < px.blue(), (
        f"expected cyan-leaning complement (red weakest), got rgb({px.red()},{px.green()},{px.blue()})"
    )


def test_silhouette_uses_skin_color(qapp):
    skin = QColor(214, 49, 49)

    def call(p, rect):
        cc_badge_paint.paint_cc_badge(
            p, rect, skin, asset_stem="dog", slot_number=1
        )

    img = _paint_to_image(96, call)
    # The silhouette should add reddish pixels somewhere near the center.
    reddish = 0
    for x in range(30, 65):
        for y in range(30, 65):
            c = img.pixelColor(x, y)
            if c.red() > 150 and c.green() < 100 and c.blue() < 100:
                reddish += 1
    assert reddish > 20, f"expected reddish silhouette pixels, found {reddish}"


def test_falls_back_to_slot_number_when_no_asset(qapp):
    skin = QColor(214, 49, 49)

    def call(p, rect):
        cc_badge_paint.paint_cc_badge(
            p, rect, skin, asset_stem=None, slot_number=3
        )

    img = _paint_to_image(64, call)
    # Verify there's text/glyph mass in the middle (some opaque pixels).
    opaque_center = sum(
        1 for x in range(20, 44) for y in range(20, 44)
        if img.pixelColor(x, y).alpha() > 50
    )
    assert opaque_center > 50, "fallback should render slot number + bg"


def test_pencil_rect_scales_with_badge_size():
    # 38px badge: 38 * 0.25 = 9.5, clamped up to 14.
    small = cc_badge_paint.pencil_rect_for(QRect(0, 0, 38, 38))
    assert small.width() == 14
    assert small.height() == 14

    # 96px badge: 96 * 0.25 = 24, within range.
    mid = cc_badge_paint.pencil_rect_for(QRect(0, 0, 96, 96))
    assert mid.width() == 24
    assert mid.height() == 24

    # 200px badge: 200 * 0.25 = 50, clamped down to 28.
    big = cc_badge_paint.pencil_rect_for(QRect(0, 0, 200, 200))
    assert big.width() == 28
    assert big.height() == 28


def test_pencil_rect_anchored_bottom_left():
    rect = cc_badge_paint.pencil_rect_for(QRect(0, 0, 100, 100))
    # Inset ~4 from bottom-left corner.
    assert rect.x() <= 6
    assert rect.x() + rect.width() < 50
    assert rect.y() + rect.height() >= 94
