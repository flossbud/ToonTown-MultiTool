"""Where a popover goes. Pure geometry in Qt logical px, global coordinates.

Popovers drop DOWN from their anchor, are kept on the screen, and flip above
the anchor only when there is no room below and there is room above.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPoint, QRect, QSize

CENTER = "center"
LEFT = "left"
SCREEN_MARGIN = 4


@dataclass(frozen=True)
class Placement:
    pos: QPoint          # top-left of the popover
    flipped: bool        # True when it opened above its anchor
    caret_x: int         # anchor centre, measured from the popover's left edge


def place_popover(anchor: QRect, size: QSize, screen: QRect, gap: int = 0,
                  align: str = CENTER, margin: int = SCREEN_MARGIN) -> Placement:
    """`anchor` is the block (or group) the popover belongs to, `gap` the
    distance between the two, `screen` the usable screen rectangle."""
    w, h = size.width(), size.height()
    if align == LEFT:
        x = anchor.left()
    else:
        x = anchor.left() + (anchor.width() - w) // 2
    y = anchor.top() + anchor.height() + gap
    flipped = False
    floor = screen.top() + screen.height() - margin
    if y + h > floor:
        above = anchor.top() - gap - h
        if above >= screen.top() + margin:
            y, flipped = above, True
        else:
            y = max(screen.top() + margin, floor - h)
    left = screen.left() + margin
    right = screen.left() + screen.width() - margin - w
    x = max(left, min(x, right)) if right >= left else left
    centre = anchor.left() + anchor.width() // 2
    caret = max(0, min(w, centre - x))
    return Placement(QPoint(x, y), flipped, caret)
