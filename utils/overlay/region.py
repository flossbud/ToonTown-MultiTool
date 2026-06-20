"""Build the transparent-mode click-through input region (QRegion) from card/emblem paths.

The region is the union of each card's painted body path (rounded rect minus the concave
bite), the emblem disc, and - while visible - the transient scale badge. Everything outside
this region is a click-through hole. Window-relative coordinates; curves are approximated by
polygon fill (sufficient for hit-testing)."""
from __future__ import annotations

from PySide6.QtCore import QRect
from PySide6.QtGui import QPainterPath, QRegion, QTransform


def _path_to_region(path: QPainterPath, transform: QTransform) -> QRegion:
    if path.isEmpty():
        return QRegion()
    polygon = path.toFillPolygon(transform).toPolygon()
    if polygon.isEmpty():
        return QRegion()
    return QRegion(polygon)


def device_input_region(path: QPainterPath, dpr: float) -> QRegion:
    """Return a device-pixel QRegion for *path* given device-pixel ratio *dpr*.

    Scales the continuous path by *dpr* BEFORE polygonizing so the polygon is
    already at device resolution.  This is the single logical->device conversion
    point; callers stay in logical coords and never see device pixels directly.

    Guards against a non-positive *dpr* (which Qt never reports, but would
    collapse or reflect the shape): a bad ratio falls back to 1.0 so the shape
    renders at logical size rather than vanishing - never crash the overlay.
    """
    if dpr <= 0:
        dpr = 1.0
    return _path_to_region(path, QTransform().scale(dpr, dpr))


def build_input_region(
    card_paths: list[QPainterPath],
    emblem_path: QPainterPath,
    transform: QTransform,
    badge_rect: QRect | None = None,
) -> QRegion:
    region = QRegion()
    for path in card_paths:
        region = region.united(_path_to_region(path, transform))
    region = region.united(_path_to_region(emblem_path, transform))
    if badge_rect is not None:
        region = region.united(QRegion(badge_rect))
    return region


def controls_region(rects_base, scale, dpr):
    """Device-pixel QRegion = union of card-local control rects scaled by scale*dpr.

    rects_base: card-local (scale-1.0) control widget QRects. scale: overlay zoom
    (the same factor the ScaledCardView transform applies). dpr: device-pixel
    ratio. Unlike `device_input_region` (one continuous path), the controls are
    DISJOINT rects, so this builds the QRegion directly (union of integer device
    rects) rather than polygonizing a single path.
    """
    region = QRegion()
    f = float(scale) * float(dpr if dpr > 0 else 1.0)
    for r in rects_base:
        dx = round(r.x() * f)
        dy = round(r.y() * f)
        dw = round(r.width() * f)
        dh = round(r.height() * f)
        if dw > 0 and dh > 0:
            region = region.united(QRegion(dx, dy, dw, dh))
    return region
