"""Card "tuck into the emblem" animation for the float cluster's Hide-Cards
toggle.

The real hide/show stays the PROVEN instant path (cells ``setVisible`` with
retained size, exact input shape, taskbar-rep re-align - see
``ClusterOverlayController.set_cards_hidden``); this module only animates
CHEAP SNAPSHOTS of the cards, never the live widgets. ``TuckGhostLayer`` is a
transient, mouse-transparent child of the borrowed ``_grid_host`` (the same
hosting pattern as the internal radial dim) that paints each card's grabbed
pixmap (plus its accent-halo pixmap from the glow cache) at a geometry
interpolated between the card's resting rect and a point-sized rect on the
emblem center. It stacks ABOVE the cards and BELOW the emblem, so the ghosts
visibly slide UNDER the emblem disc - the same "into the emblem" motion as
the radial spokes' fly-back, which the hide animation runs in step with.

Being a child of the transformed host, the layer scales/moves with any
cluster zoom or drag automatically - all geometry here is framed-1.0 host
coords, exactly like the internal dim.

Progress convention: 0.0 = cards at rest, 1.0 = fully tucked. The HIDE
animation drives 0 -> 1 (ease-in, the ring's fly-back feel) and the SHOW
animation drives 1 -> 0 (ease-out, the ring's fly-out feel). Easing is
applied ONCE by the driving QVariantAnimation's curve; the helpers below are
LINEAR in progress (applying a curve here too would double-ease - the
radial dim's documented lesson).
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QWidget

# Durations match the radial ring's fly-back/fly-out so the cards and the
# dismissing ring move as one system (RadialMenuWidget._CLOSE_MS/_APPEAR_MS).
TUCK_HIDE_MS = 240
TUCK_SHOW_MS = 360

_MIN_SCALE = 0.05    # never collapse to a degenerate zero-size rect
_FADE_START = 0.55   # fully opaque until here; the emblem disc covers the rest


def _clamp01(t: float) -> float:
    return 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)


def tuck_scale(progress: float) -> float:
    """Ghost scale factor at ``progress``: 1.0 at rest -> _MIN_SCALE tucked."""
    return 1.0 - (1.0 - _MIN_SCALE) * _clamp01(progress)


def tuck_opacity(progress: float) -> float:
    """Ghost opacity at ``progress``: opaque through most of the travel (the
    shrinking card should read as a solid object being put away), fading only
    over the final stretch so edges peeking past the emblem disc land soft."""
    p = _clamp01(progress)
    if p <= _FADE_START:
        return 1.0
    return 1.0 - (p - _FADE_START) / (1.0 - _FADE_START)


def tuck_rect(rect: QRectF, emblem_center: QPointF, progress: float) -> QRectF:
    """``rect`` scaled by ``tuck_scale(progress)`` about its own center, with
    that center lerped toward ``emblem_center``. Applying this to a card rect
    AND to its (concentric) halo rect with the same progress keeps the pair
    rigidly locked together through the whole tuck."""
    p = _clamp01(progress)
    k = tuck_scale(p)
    c = rect.center()
    cx = c.x() + (emblem_center.x() - c.x()) * p
    cy = c.y() + (emblem_center.y() - c.y()) * p
    w = rect.width() * k
    h = rect.height() * k
    return QRectF(cx - w / 2.0, cy - h / 2.0, w, h)


class TuckGhostLayer(QWidget):
    """Paints the tucking card ghosts. Specs are dicts:
    ``{"pm": QPixmap, "rect": QRectF, "halo_pm": QPixmap|None,
    "halo_rect": QRectF|None}`` with rects in framed-1.0 host coords (the
    card's/halo's resting geometry - progress 0 reproduces the live pixels
    exactly, which is what makes the show-path's end-of-flight swap to the
    real cells invisible)."""

    def __init__(self, parent, emblem_center: QPointF) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setStyleSheet("background: transparent;")
        self._emblem_center = QPointF(emblem_center)
        self._specs: list = []
        self._progress = 0.0

    def set_specs(self, specs) -> None:
        self._specs = list(specs)
        self.update()

    def set_progress(self, progress: float) -> None:
        self._progress = _clamp01(float(progress))
        self.update()

    def progress(self) -> float:
        return self._progress

    def paintEvent(self, ev) -> None:
        if not self._specs:
            return
        opacity = tuck_opacity(self._progress)
        if opacity <= 0.0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.setOpacity(opacity)
        for s in self._specs:
            halo_pm, halo_rect = s.get("halo_pm"), s.get("halo_rect")
            if halo_pm is not None and halo_rect is not None:
                p.drawPixmap(tuck_rect(halo_rect, self._emblem_center, self._progress),
                             halo_pm, QRectF(halo_pm.rect()))
            pm = s["pm"]
            p.drawPixmap(tuck_rect(s["rect"], self._emblem_center, self._progress),
                         pm, QRectF(pm.rect()))
        p.end()
