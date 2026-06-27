"""Pure snapshot helpers for the overlay scale gesture proxy.

This module is intentionally pure: it deals only in geometry (QRect/QPoint) and
images (QImage), with no widgets, windows, or controller imports. That keeps it
fully unit-testable offscreen and free of any X11 / window-manager coupling.

The scale gesture captures the cluster of overlay surfaces into a single
composited snapshot and zooms that snapshot, rather than live-resizing the real
windows. These helpers compute the cluster bounding box, compose the snapshot
image (honoring device pixel ratio and a hard physical-size cap), and describe
the bbox-local regions where the proxy still accepts wheel events.
"""

from dataclasses import dataclass

from PySide6.QtCore import QRect, QPoint
from PySide6.QtGui import QImage, QPainter


@dataclass(frozen=True)
class Layer:
    """One source surface to be composited into the snapshot.

    ``image`` is the surface's pixels and ``top_left`` is its position in
    cluster/screen logical coordinates.
    """

    image: QImage
    top_left: QPoint


def cluster_bbox(rects: list[QRect]) -> QRect:
    """Return the union (bounding rect) of ``rects``.

    An empty list yields a null/empty ``QRect()``.
    """
    if not rects:
        return QRect()
    result = QRect(rects[0])
    for r in rects[1:]:
        result = result.united(r)
    return result


def compose_snapshot(
    layers: list[Layer], bbox: QRect, dpr: float, max_px: int = 8192
) -> QImage:
    """Composite ``layers`` into a single transparent ARGB32-premultiplied image.

    The returned image's PHYSICAL size is ``round(bbox.width()*dpr)`` x
    ``round(bbox.height()*dpr)`` with ``setDevicePixelRatio(dpr)``, filled fully
    transparent. Each layer is painted back-to-front (list order) at its
    bbox-local logical offset (``layer.top_left - bbox.topLeft()``).

    SIZE CAP: if either physical dimension would exceed ``max_px`` it is clamped
    to ``max_px`` (dpr is preserved; the logical area beyond the cap is simply
    not represented). Each dimension is at least 1px.
    """
    phys_w = max(1, min(max_px, round(bbox.width() * dpr)))
    phys_h = max(1, min(max_px, round(bbox.height() * dpr)))

    img = QImage(phys_w, phys_h, QImage.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(dpr)
    img.fill(0)

    origin = bbox.topLeft()
    painter = QPainter(img)
    try:
        for layer in layers:
            offset = layer.top_left - origin
            painter.drawImage(offset, layer.image)
    finally:
        painter.end()

    return img


def wheel_zone_rects(
    bbox: QRect, emblem: QRect, radial: QRect | None, inflate: int
) -> list[QRect]:
    """Return bbox-local rects where the proxy should accept wheel events.

    Always includes the ``emblem`` rect (translated to bbox-local) inflated by
    ``inflate`` on every side. When ``radial`` is not ``None`` its rect is also
    included, translated to bbox-local but NOT inflated.
    """
    origin = bbox.topLeft()
    rects: list[QRect] = []

    emblem_local = emblem.translated(-origin.x(), -origin.y())
    rects.append(emblem_local.adjusted(-inflate, -inflate, inflate, inflate))

    if radial is not None:
        rects.append(radial.translated(-origin.x(), -origin.y()))

    return rects
