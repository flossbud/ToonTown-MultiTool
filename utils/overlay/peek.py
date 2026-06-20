# utils/overlay/peek.py
"""Pure helpers for overlay hover-peek detection (no Qt).

`peeking_indices` answers "which cards have a cursor over them" given cursor
points and card rects. `GhostPointStore` accumulates the latest click-sync
ghost-cursor position per slot from the service's ghost_pointer_event payloads.
Both are pure so they unit-test without a QApplication.
"""
from __future__ import annotations


def peeking_indices(points, rects) -> set:
    """Return the set of rect indices that contain at least one point.

    points: iterable of (x, y). rects: iterable of (x, y, w, h). A rect contains
    a point when x <= px < x+w and y <= py < y+h (top/left inclusive, bottom/right
    exclusive - matches Qt's pixel coverage).
    """
    pts = list(points)
    result = set()
    for i, (rx, ry, rw, rh) in enumerate(rects):
        for (px, py) in pts:
            if rx <= px < rx + rw and ry <= py < ry + rh:
                result.add(i)
                break
    return result


class GhostPointStore:
    """Latest ghost-cursor point per slot, fed from ghost_pointer_event payloads.

    Payload shape (from services/click_sync_service.py):
        ("motion", [(slot, global_x, global_y), ...])
        ("release", [(slot, global_x, global_y), ...])
    "motion" upserts each slot's point; "release" drops those slots; clear()
    drops everything (use on ghost_clear). Any other kind (e.g. "press") and any
    malformed payload are silently ignored - peek only tracks live positions.
    """

    def __init__(self):
        self._by_slot: dict[int, tuple[int, int]] = {}

    def ingest(self, payload) -> None:
        try:
            kind, items = payload
        except (TypeError, ValueError):
            return
        if kind == "motion":
            for slot, x, y in items:
                self._by_slot[slot] = (int(x), int(y))
        elif kind == "release":
            for slot, *_rest in items:
                self._by_slot.pop(slot, None)

    def clear(self) -> None:
        self._by_slot.clear()

    def points(self) -> list:
        return list(self._by_slot.values())
