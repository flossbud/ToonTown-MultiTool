from __future__ import annotations

# Px of movement that turns a press into a drag rather than a click. 10 is
# Qt's own startDragDistance() convention; the previous 5 misclassified real
# clicks as drags (live on macOS 2026-07-03: 2-3 emblem clicks in a row
# traced dragging=True from ordinary hand drift, so the windowed wheel
# "randomly" refused to open).
DRAG_THRESHOLD = 10


def is_drag(start, current) -> bool:
    """Return True if the pointer moved more than DRAG_THRESHOLD pixels in any axis."""
    return (abs(current.x() - start.x()) > DRAG_THRESHOLD or
            abs(current.y() - start.y()) > DRAG_THRESHOLD)
