from __future__ import annotations

DRAG_THRESHOLD = 5  # px of movement that turns a press into a drag rather than a click


def is_drag(start, current) -> bool:
    """Return True if the pointer moved more than DRAG_THRESHOLD pixels in any axis."""
    return (abs(current.x() - start.x()) > DRAG_THRESHOLD or
            abs(current.y() - start.y()) > DRAG_THRESHOLD)
