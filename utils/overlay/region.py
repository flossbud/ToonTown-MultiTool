"""Build the transparent-mode click-through input region (QRegion) from card/emblem paths.

The region is the union of each card's painted body path (rounded rect minus the concave
bite), the emblem disc, and - while visible - the transient scale badge. Everything outside
this region is a click-through hole. Window-relative coordinates; curves are approximated by
polygon fill (sufficient for hit-testing).

`controls_region` is a separate entry point for transparent peek mode: the union of
a card's individual control-widget rects (disjoint device-pixel rects, not a single
continuous path), so only the buttons block clicks and the body stays click-through."""
from __future__ import annotations

from PySide6.QtCore import QRect, QRectF, QPointF, Qt
from PySide6.QtGui import QPainterPath, QRegion, QTransform, QPixmap, QPainter


def compose_dim_source(
    side: int,
    dpr: float,
    placements: list[tuple[float, float, QPixmap | None]],
) -> QPixmap | None:
    """Composite grabbed card pixmaps into one ``side`` x ``side`` (LOGICAL)
    source pixmap for the radial dim, in logical coords with device-pixel backing.

    side: logical edge of the dim square. dpr: device-pixel ratio. placements:
    iterable of ``(logical_dx, logical_dy, card_pixmap)`` where (dx, dy) is the
    card's top-left RELATIVE to the dim square's top-left. Each card_pixmap
    already carries its own devicePixelRatio (from ``QWidget.grab()``); it is
    drawn at its device-INDEPENDENT size so dpr is applied exactly once (no
    double scale). Uncovered area stays transparent so the frost base shows
    through there. Returns None for non-positive side/dpr, no placements, or
    when every placement is a null/None card (nothing to composite)."""
    placements = list(placements or [])
    if side <= 0 or dpr <= 0 or not placements:
        return None
    phys = int(round(side * dpr))
    pm = QPixmap(phys, phys)
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.SmoothPixmapTransform, True)
    drawn = 0
    for dx, dy, card in placements:
        if card is None or card.isNull():
            continue
        # target rect = LOGICAL; source rect = the FULL grabbed pixmap in its own
        # pixel coords. The dpr-backed canvas maps logical->physical once.
        target = QRectF(QPointF(float(dx), float(dy)), card.deviceIndependentSize())
        p.drawPixmap(target, card, QRectF(card.rect()))
        drawn += 1
    p.end()
    if drawn == 0:
        return None          # every card was null -> no source (frost-base only)
    return pm


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


def controls_region(rects_base: list[QRect], scale: float, dpr: float) -> QRegion:
    """Device-pixel QRegion = union of card-local control rects scaled by scale*dpr.

    rects_base: card-local (scale-1.0) control widget QRects. scale: overlay zoom
    (the same factor the ScaledCardView transform applies). dpr: device-pixel
    ratio. Unlike `device_input_region` (one continuous path), the controls are
    DISJOINT rects, so this builds the QRegion directly (union of integer device
    rects) rather than polygonizing a single path.
    """
    region = QRegion()
    device_scale = float(scale) * float(dpr if dpr > 0 else 1.0)
    for r in rects_base:
        dx = round(r.x() * device_scale)
        dy = round(r.y() * device_scale)
        dw = round(r.width() * device_scale)
        dh = round(r.height() * device_scale)
        if dw > 0 and dh > 0:
            region = region.united(QRegion(dx, dy, dw, dh))
    return region
