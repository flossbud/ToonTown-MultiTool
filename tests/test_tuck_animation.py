"""Pure geometry/opacity helpers + ghost-layer paint for the card tuck
animation (Hide-Cards). The interpolation must be LINEAR in progress (easing
is applied once by the driving animation's curve), progress 0 must reproduce
the resting card pixels exactly (the show-path swap relies on it), and
concentric card/halo rects must stay locked together through the tuck."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import pytest
from PySide6.QtCore import QPoint, QPointF, QRectF
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from utils.overlay.tuck_animation import (
    TUCK_HIDE_MS, TUCK_SHOW_MS, _MIN_SCALE, TuckGhostLayer,
    tuck_opacity, tuck_rect, tuck_scale)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_tuck_scale_endpoints_and_monotonic():
    assert tuck_scale(0.0) == 1.0
    assert tuck_scale(1.0) == pytest.approx(_MIN_SCALE)
    samples = [tuck_scale(p / 10.0) for p in range(11)]
    assert all(a > b for a, b in zip(samples, samples[1:]))
    assert tuck_scale(-1.0) == 1.0                      # clamped
    assert tuck_scale(2.0) == pytest.approx(_MIN_SCALE)


def test_tuck_opacity_holds_then_fades():
    assert tuck_opacity(0.0) == 1.0
    assert tuck_opacity(0.55) == 1.0                    # opaque through travel
    assert 0.0 < tuck_opacity(0.8) < 1.0
    assert tuck_opacity(1.0) == pytest.approx(0.0)


def test_tuck_rect_endpoints():
    rect = QRectF(10.0, 20.0, 200.0, 100.0)
    emblem = QPointF(400.0, 300.0)
    assert tuck_rect(rect, emblem, 0.0) == rect         # rest = live pixels
    end = tuck_rect(rect, emblem, 1.0)
    assert end.center().x() == pytest.approx(emblem.x())
    assert end.center().y() == pytest.approx(emblem.y())
    assert end.width() == pytest.approx(200.0 * _MIN_SCALE)
    assert end.height() == pytest.approx(100.0 * _MIN_SCALE)


def test_concentric_rects_stay_locked():
    """A halo rect (card rect + pad) shares the card's center, so applying the
    same progress must keep the pair concentric at every step - the halo may
    never drift off its card mid-tuck."""
    card = QRectF(50.0, 60.0, 180.0, 120.0)
    halo = card.adjusted(-40.0, -40.0, 40.0, 40.0)
    emblem = QPointF(500.0, 400.0)
    for p in (0.0, 0.25, 0.5, 0.75, 1.0):
        c = tuck_rect(card, emblem, p).center()
        g = tuck_rect(halo, emblem, p).center()
        assert c.x() == pytest.approx(g.x())
        assert c.y() == pytest.approx(g.y())


def test_durations_match_radial_motion():
    from utils.overlay.radial_menu import RadialMenuWidget
    assert TUCK_HIDE_MS == RadialMenuWidget._CLOSE_MS
    assert TUCK_SHOW_MS == RadialMenuWidget._APPEAR_MS


def test_ghost_layer_paints_specs_without_crash(qapp):
    layer = TuckGhostLayer(None, QPointF(200.0, 200.0))
    layer.resize(400, 400)
    pm = QPixmap(120, 80)
    pm.fill(QColor("#3080ff"))
    halo = QPixmap(160, 120)
    halo.fill(QColor(255, 100, 200, 90))
    layer.set_specs([
        {"pm": pm, "rect": QRectF(20, 20, 120, 80),
         "halo_pm": halo, "halo_rect": QRectF(0, 0, 160, 120)},
        {"pm": pm, "rect": QRectF(240, 280, 120, 80),
         "halo_pm": None, "halo_rect": None},
    ])
    for p in (0.0, 0.4, 0.7, 1.0):
        layer.set_progress(p)
        target = QPixmap(400, 400)
        target.fill(QColor(0, 0, 0, 0))
        painter = QPainter(target)
        layer.render(painter, QPoint(0, 0))
        painter.end()


def test_ghost_layer_empty_specs_is_noop(qapp):
    layer = TuckGhostLayer(None, QPointF(100.0, 100.0))
    layer.resize(200, 200)
    layer.set_progress(0.5)
    target = QPixmap(200, 200)
    painter = QPainter(target)
    layer.render(painter, QPoint(0, 0))
    painter.end()
