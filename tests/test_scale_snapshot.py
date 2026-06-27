"""Unit tests for the pure snapshot helpers in utils/overlay/scale_snapshot.py.

These are pure geometry/image helpers (no widgets, no windows) so they run
fully offscreen. The session ``qapp`` fixture is required wherever a QImage or
QPainter is constructed.
"""

from PySide6.QtCore import QRect, QPoint

from utils.overlay.scale_snapshot import (
    Layer,
    cluster_bbox,
    compose_snapshot,
    wheel_zone_rects,
)


def _solid(w, h, color):
    from PySide6.QtGui import QImage, QColor

    im = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    im.fill(QColor(color))
    return im


def test_cluster_bbox_unions_rects():
    rects = [
        QRect(0, 0, 10, 10),
        QRect(50, 50, 10, 10),
        QRect(-5, 20, 5, 5),
    ]
    bbox = cluster_bbox(rects)
    # union spans x in [-5, 60), y in [0, 60)
    assert bbox == QRect(-5, 0, 65, 60)


def test_cluster_bbox_empty_is_null():
    bbox = cluster_bbox([])
    assert bbox.isEmpty()
    assert bbox == QRect()


def test_compose_places_layers_at_bbox_relative_offsets(qapp):
    bbox = QRect(100, 100, 80, 80)
    layers = [
        Layer(image=_solid(20, 20, "red"), top_left=QPoint(100, 100)),
        Layer(image=_solid(20, 20, "blue"), top_left=QPoint(150, 150)),
    ]
    img = compose_snapshot(layers, bbox, dpr=1.0)

    red = img.pixelColor(5, 5)
    assert (red.red(), red.green(), red.blue()) == (255, 0, 0)

    blue = img.pixelColor(55, 55)
    assert (blue.red(), blue.green(), blue.blue()) == (0, 0, 255)

    # a gap with no layer is fully transparent
    gap = img.pixelColor(40, 40)
    assert gap.alpha() == 0


def test_compose_honors_integer_dpr(qapp):
    bbox = QRect(0, 0, 30, 40)
    layers = [Layer(image=_solid(30, 40, "red"), top_left=QPoint(0, 0))]
    img = compose_snapshot(layers, bbox, dpr=2.0)
    assert img.devicePixelRatio() == 2.0
    assert img.width() == 60
    assert img.height() == 80


def test_compose_fractional_dpr_rounds_up(qapp):
    # 99 * 1.25 = 123.75 -> round() = 124 (truncation/int would give 123).
    # Hardcoded literal (not round(99*1.25)) so the assertion is not tautological.
    bbox = QRect(0, 0, 99, 99)
    img = compose_snapshot([], bbox, dpr=1.25)
    assert img.devicePixelRatio() == 1.25
    assert img.width() == 124
    assert img.height() == 124


def test_compose_fractional_dpr_rounds_down(qapp):
    # 101 * 1.25 = 126.25 -> round() = 126 (ceil would give 127). Pins round()
    # from both directions together with the rounds_up test above.
    bbox = QRect(0, 0, 101, 101)
    img = compose_snapshot([], bbox, dpr=1.25)
    assert img.width() == 126
    assert img.height() == 126


def test_compose_size_cap_clamps_physical_dims(qapp):
    bbox = QRect(0, 0, 200, 200)
    img = compose_snapshot([], bbox, dpr=1.0, max_px=100)
    assert img.width() == 100          # exact cap value, not just <= 100
    assert img.height() == 100


def test_wheel_zone_emblem_inflated_bbox_local(qapp):
    bbox = QRect(100, 100, 200, 200)
    emblem = QRect(150, 150, 40, 40)
    rects = wheel_zone_rects(bbox, emblem, None, inflate=10)
    # emblem translated to bbox-local is (50, 50, 40, 40), inflated by 10
    assert rects == [QRect(40, 40, 60, 60)]


def test_wheel_zone_includes_radial_when_open(qapp):
    bbox = QRect(100, 100, 200, 200)
    emblem = QRect(150, 150, 40, 40)
    radial = QRect(120, 120, 80, 80)
    rects = wheel_zone_rects(bbox, emblem, radial, inflate=10)
    assert rects[0] == QRect(40, 40, 60, 60)
    # radial translated to bbox-local, NOT inflated
    assert rects[1] == QRect(20, 20, 80, 80)
    assert len(rects) == 2


def test_wheel_zone_excludes_radial_when_none(qapp):
    bbox = QRect(0, 0, 100, 100)
    emblem = QRect(10, 10, 20, 20)
    rects = wheel_zone_rects(bbox, emblem, None, inflate=5)
    assert len(rects) == 1
