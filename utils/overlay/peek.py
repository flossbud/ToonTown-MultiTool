# utils/overlay/peek.py
"""Pure helpers for overlay hover-peek detection (no Qt).

`peeking_indices` answers "which cards have a cursor over them" given cursor
points and card rects. `control_hits` maps cursor points to the specific card
control each lands on (for ghost-cursor clicks). `GhostPointStore` accumulates
the latest click-sync ghost-cursor position per slot from the service's
ghost_pointer_event payloads. All are pure so they unit-test without a QApplication.
"""
from __future__ import annotations


def peeking_indices(points, rects, cutouts=None) -> set:
    """Return the set of rect indices that contain at least one point.

    points: iterable of (x, y). rects: iterable of (x, y, w, h). A rect contains
    a point when x <= px < x+w and y <= py < y+h (top/left inclusive, bottom/right
    exclusive - matches Qt's pixel coverage).

    cutouts: optional iterable parallel to rects, each entry a (cx, cy, r)
    circle (same coordinate space as rects/points) or None. A point strictly
    inside a rect's cutout circle does NOT count as containment: the card's
    painted body is the rect MINUS the concave corner carve the emblem nests
    in, so a cursor on the emblem must never read as hovering the card.
    """
    pts = list(points)
    cuts = list(cutouts) if cutouts is not None else []
    result = set()
    for i, (rx, ry, rw, rh) in enumerate(rects):
        cut = cuts[i] if i < len(cuts) else None
        for (px, py) in pts:
            if not (rx <= px < rx + rw and ry <= py < ry + rh):
                continue
            if cut is not None:
                cx, cy, r = cut
                if (px - cx) ** 2 + (py - cy) ** 2 < r * r:
                    continue
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


def control_hits(points, cards, scale) -> list:
    """Map logical ghost points to the card control each lands on.

    points: iterable of (x, y) in LOGICAL global coords.
    cards: iterable of (surface_id, surface_rect, control_rects) where
        surface_rect is (x, y, w, h) in logical global coords and control_rects
        is a list of (x, y, w, h) in CARD-LOCAL (scale-1.0) coords.
    scale: the group zoom the card content is rendered at.

    Returns [(surface_id, local_x, local_y), ...] - one entry per point that
    falls inside a control of its containing card. Card-local =
    round((global - surface_origin) / scale). Cards do not overlap, so the first
    card that contains the point wins; a point in the body (no control) yields
    nothing. Pure - no Qt."""
    s = float(scale) if scale else 1.0
    if s <= 0:
        s = 1.0
    cards = list(cards)  # re-scanned per point; never let a generator exhaust
    hits = []
    for (px, py) in points:
        for (surface_id, (sx, sy, sw, sh), control_rects) in cards:
            if not (sx <= px < sx + sw and sy <= py < sy + sh):
                continue
            lx = round((px - sx) / s)
            ly = round((py - sy) / s)
            for (cx, cy, cw, ch) in control_rects:
                if cx <= lx < cx + cw and cy <= ly < cy + ch:
                    hits.append((surface_id, lx, ly))
                    break
            break  # containing card found; cards do not overlap
    return hits
