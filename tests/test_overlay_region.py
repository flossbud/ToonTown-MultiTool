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


def test_no_root_capture_or_kwin_blur_symbols():
    """Guard: the rejected root-grab / KWin-atom / rectangle-band approaches must
    never reappear anywhere in the overlay package."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "utils" / "overlay"
    banned = ("grabWindow", "set_blur_behind", "_KDE_NET_WM_BLUR_BEHIND_REGION",
              "circle_blur_rects")
    hits = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in banned:
            if token in text:
                hits.append(f"{path.name}: {token}")
    assert hits == [], f"banned overlay symbols present: {hits}"
