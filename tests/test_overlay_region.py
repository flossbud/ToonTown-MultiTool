from PySide6.QtCore import QPoint, QRectF, QPointF
from PySide6.QtGui import QPainterPath, QTransform
from utils.overlay.region import build_input_region

def _card(x, y, w, h, bite_center, bite_r=96.0, radius=20.0):
    p = QPainterPath()
    p.addRoundedRect(QRectF(x, y, w, h), radius, radius)
    bite = QPainterPath()
    bite.addEllipse(bite_center, bite_r, bite_r)
    return p.subtracted(bite)

def test_point_inside_card_is_in_region():
    card = _card(0, 0, 200, 232, QPointF(200, 232))  # bite at bottom-right corner
    region = build_input_region([card], QPainterPath(), QTransform())
    assert region.contains(QPoint(40, 40)) is True

def test_point_in_gap_is_excluded():
    card = _card(0, 0, 200, 232, QPointF(200, 232))
    region = build_input_region([card], QPainterPath(), QTransform())
    assert region.contains(QPoint(400, 400)) is False  # far gap, no card here

def test_bite_corner_is_excluded():
    card = _card(0, 0, 200, 232, QPointF(200, 232))
    region = build_input_region([card], QPainterPath(), QTransform())
    # deep inside the carved 96px circle at the bottom-right corner -> hole
    assert region.contains(QPoint(192, 224)) is False

def test_scale_transform_moves_region():
    card = _card(0, 0, 100, 100, QPointF(999, 999))  # bite far away -> plain rounded rect
    region = build_input_region([card], QPainterPath(), QTransform().scale(2.0, 2.0))
    assert region.contains(QPoint(150, 150)) is True   # (75,75) in card space -> (150,150) scaled
    assert region.contains(QPoint(40, 40)) is True

def test_badge_rect_added():
    from PySide6.QtCore import QRect
    region = build_input_region([], QPainterPath(), QTransform(), badge_rect=QRect(500, 500, 60, 24))
    assert region.contains(QPoint(510, 510)) is True


def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_compose_dim_source_none_cases():
    _app()
    from PySide6.QtGui import QPixmap
    from utils.overlay.region import compose_dim_source
    assert compose_dim_source(0, 2.0, [(0, 0, QPixmap(10, 10))]) is None
    assert compose_dim_source(200, 0, [(0, 0, QPixmap(10, 10))]) is None
    assert compose_dim_source(200, 2.0, []) is None


def test_compose_dim_source_dpr_invariant():
    _app()
    from PySide6.QtGui import QPixmap, QColor
    from utils.overlay.region import compose_dim_source
    card = QPixmap(20, 20); card.fill(QColor(0, 255, 0))
    src = compose_dim_source(200, 2.0, [(0, 0, card)])
    assert src is not None
    assert src.size().width() == 400 and src.size().height() == 400   # physical
    assert abs(src.deviceIndependentSize().width() - 200.0) < 0.5      # logical
    assert abs(src.devicePixelRatio() - 2.0) < 1e-6


def test_compose_dim_source_no_double_scale_at_dpr2():
    _app()
    from PySide6.QtGui import QPixmap, QColor
    from utils.overlay.region import compose_dim_source
    # a 50x50-LOGICAL card (100x100 physical) at dpr 2, solid red, placed at
    # logical offset (10, 10) inside a 200-logical disc.
    card = QPixmap(100, 100); card.setDevicePixelRatio(2.0); card.fill(QColor(255, 0, 0))
    src = compose_dim_source(200, 2.0, [(10, 10, card)])
    assert src is not None
    img = src.toImage()
    # Correct placement: card occupies logical [10,60) -> physical [20,120).
    assert img.pixelColor(30, 30).red() > 200       # phys (30,30) == logical (15,15): inside card
    # Double-scaled bug would draw the card at logical [10,110) -> physical [20,220),
    # so physical (150,150) would be red. Correct rendering leaves it transparent.
    assert img.pixelColor(150, 150).alpha() == 0


def test_compose_dim_source_offset_placement():
    _app()
    from PySide6.QtGui import QPixmap, QColor
    from utils.overlay.region import compose_dim_source
    card = QPixmap(40, 40); card.fill(QColor(0, 0, 255))   # dpr 1
    src = compose_dim_source(200, 1.0, [(10, 20, card)])   # offset (10,20)
    assert src is not None
    img = src.toImage()
    assert img.pixelColor(15, 25).blue() > 200     # inside the placed card
    assert img.pixelColor(2, 2).alpha() == 0       # outside the card -> transparent
