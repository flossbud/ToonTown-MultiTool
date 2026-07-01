"""Pure cluster geometry helpers for the single-window cluster overlay.

All math here is stateless QRect/QRegion arithmetic - no widget state, no Qt
event loop - so it is fully unit-testable under the offscreen QPA. Callers
work entirely in either cluster-local or screen coordinates as documented per
function; this module never touches device pixels or DPR.

The load-bearing invariant lives in :func:`window_rect_for`: the single cluster
window is positioned so the EMBLEM CENTER lands exactly on the anchor screen
point, regardless of where the emblem sits within the cluster subtree. Naively
centering the bounding box on the anchor is WRONG whenever the emblem is
off-center; do not "simplify" it back to that.

Transform scaling (fixed-envelope model): the cluster window is sized ONCE to
the :func:`envelope_for` rect - the bounding box of the scaled cluster at
SCALE_MAX, pivoted on the emblem center - and NEVER resized or moved during a
scale gesture. The live host stays at its framed 1.0 layout and is zoomed by a
single uniform transform about the pivot; :func:`map_host_rect_to_window` /
:func:`map_window_point_to_host` convert between the 1.0 host coordinates and
the window coordinates that transform produces. Window geometry changing on a
scale notch was the judder (an XWayland resize+move is never atomic); keeping
the envelope fixed removes it by construction.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Tuple

from PySide6.QtCore import QRect
from PySide6.QtGui import QRegion


def cluster_bbox(card_rects: list[QRect]) -> QRect:
    """Return the union (bounding rect) of *card_rects* in cluster-local coords.

    An empty list yields a null ``QRect()``.
    """
    bbox = QRect()
    for rect in card_rects:
        # QRect(rect) COPIES so the single/first-rect path never aliases (and
        # later mutates) the caller's input; .united() already returns a new rect.
        bbox = QRect(rect) if bbox.isNull() else bbox.united(rect)
    return bbox


def window_rect_for(
    cluster_bbox_size: Tuple[int, int],
    emblem_center_local: Tuple[int, int],
    anchor: Tuple[int, int],
) -> QRect:
    """Compute the SCREEN rect for the single cluster window.

    The window is sized to the cluster subtree and placed so the emblem center
    sits exactly on *anchor*. Relative to the emblem center the cluster subtree
    extends ``left=ex``, ``right=w-ex``, ``top=ey``, ``bottom=h-ey``, so the
    window hugs the bbox exactly and the emblem center lands on the anchor.

    Args:
        cluster_bbox_size: ``(w, h)`` of the cluster subtree.
        emblem_center_local: ``(ex, ey)`` emblem center within the subtree
            (top-left origin).
        anchor: ``(ax, ay)`` screen point the emblem center must occupy.

    Returns:
        The screen ``QRect`` for the window, with
        ``(rect.x() + ex, rect.y() + ey) == anchor``.
    """
    w, h = cluster_bbox_size
    ex, ey = emblem_center_local
    ax, ay = anchor

    left = ex
    right = w - ex
    top = ey
    bottom = h - ey

    width = left + right
    height = top + bottom

    return QRect(ax - left, ay - top, width, height)


def envelope_for(
    cluster_size: Tuple[int, int],
    emblem_center_local: Tuple[int, int],
    max_scale: float,
) -> Tuple[Tuple[int, int], Tuple[int, int]]:
    """Size the fixed cluster window envelope and locate the zoom pivot in it.

    The envelope is the bounding box of the cluster scaled by *max_scale* about
    the emblem center: relative to the emblem center the 1.0 host extends
    ``left=ex``/``right=w-ex``/``top=ey``/``bottom=h-ey``, so at *max_scale*
    each extent grows by that factor. Extents are ceil'd independently so the
    scaled content can never clip at SCALE_MAX by a sub-pixel.

    Args:
        cluster_size: ``(w, h)`` of the host subtree at scale 1.0.
        emblem_center_local: ``(ex, ey)`` emblem center within the 1.0 host.
        max_scale: the largest scale the envelope must contain (SCALE_MAX).

    Returns:
        ``((width, height), (pivot_x, pivot_y))`` - the envelope size and the
        fixed window-local point the emblem center sits on at EVERY scale.
    """
    w, h = cluster_size
    ex, ey = emblem_center_local
    left = math.ceil(ex * max_scale)
    top = math.ceil(ey * max_scale)
    right = math.ceil((w - ex) * max_scale)
    bottom = math.ceil((h - ey) * max_scale)
    return ((left + right, top + bottom), (left, top))


def map_host_rect_to_window(
    rect: QRect,
    emblem_center_local: Tuple[int, int],
    pivot: Tuple[int, int],
    scale: float,
) -> QRect:
    """Map a host-local (scale-1.0) rect into window coords under the transform.

    The transform scales about the emblem center ``(ex, ey)`` and pins that
    point onto the window-local *pivot*:
    ``window = pivot + (host - emblem_center) * scale``. Edges are rounded
    OUTWARD (floor near, ceil far) so a mapped input/hit rect always CONTAINS
    the true scaled rect - a clickable control can end up 1px generous, never
    1px dead.

    Args:
        rect: host-local rect at scale 1.0.
        emblem_center_local: ``(ex, ey)`` emblem center within the 1.0 host.
        pivot: ``(px, py)`` fixed window-local point the emblem center sits on.
        scale: the current uniform cluster scale.

    Returns:
        The window-local ``QRect`` covering *rect* under the transform.
    """
    ex, ey = emblem_center_local
    px, py = pivot
    s = float(scale)
    left = px + (rect.x() - ex) * s
    top = py + (rect.y() - ey) * s
    right = px + (rect.x() + rect.width() - ex) * s
    bottom = py + (rect.y() + rect.height() - ey) * s
    x0, y0 = math.floor(left), math.floor(top)
    return QRect(x0, y0, math.ceil(right) - x0, math.ceil(bottom) - y0)


def map_window_point_to_host(
    point: Tuple[int, int],
    emblem_center_local: Tuple[int, int],
    pivot: Tuple[int, int],
    scale: float,
) -> Tuple[int, int]:
    """Inverse of :func:`map_host_rect_to_window` for a single point.

    ``host = emblem_center + (window - pivot) / scale``, rounded to the nearest
    host pixel. A non-positive *scale* is treated as 1.0 (defensive; the scale
    machinery clamps to SCALE_MIN well above zero).

    Args:
        point: ``(x, y)`` window-local point.
        emblem_center_local: ``(ex, ey)`` emblem center within the 1.0 host.
        pivot: ``(px, py)`` fixed window-local pivot.
        scale: the current uniform cluster scale.

    Returns:
        ``(x, y)`` in host-local scale-1.0 coordinates.
    """
    ex, ey = emblem_center_local
    px, py = pivot
    s = float(scale) if scale and scale > 0 else 1.0
    x, y = point
    return (round(ex + (x - px) / s), round(ey + (y - py) / s))


def scaled_content_rect(
    cluster_size: Tuple[int, int],
    emblem_center_local: Tuple[int, int],
    anchor: Tuple[int, int],
    scale: float,
) -> QRect:
    """The SCREEN rect the scaled cluster content actually covers.

    With a fixed max-scale envelope window, the window rect overstates the
    visible content at any scale below SCALE_MAX - clamping the WINDOW to the
    screen envelope would let all visible content slide fully off-screen. Move
    clamping must therefore operate on this content rect: the 1.0 host scaled
    about the emblem center, with that center pinned on *anchor*. Rounded
    outward (floor near, ceil far) so the clamp is never a pixel too permissive.

    Args:
        cluster_size: ``(w, h)`` of the host subtree at scale 1.0.
        emblem_center_local: ``(ex, ey)`` emblem center within the 1.0 host.
        anchor: ``(ax, ay)`` screen point the emblem center occupies.
        scale: the current uniform cluster scale.

    Returns:
        The screen ``QRect`` covering the visible cluster content.
    """
    w, h = cluster_size
    ex, ey = emblem_center_local
    ax, ay = anchor
    s = float(scale)
    left = ax - ex * s
    top = ay - ey * s
    right = ax + (w - ex) * s
    bottom = ay + (h - ey) * s
    x0, y0 = math.floor(left), math.floor(top)
    return QRect(x0, y0, math.ceil(right) - x0, math.ceil(bottom) - y0)


def input_union(
    emblem_rect: QRect,
    card_controls: Mapping[object, list[QRect]],
    visible: Iterable[object],
) -> QRegion:
    """Union of the emblem rect with the control rects of *visible* slots only.

    Args:
        emblem_rect: the always-present emblem hit rect (window-local coords).
        card_controls: ``{slot_id: [QRect, ...]}`` control rects per slot
            (window-local coords).
        visible: slot ids whose controls should block input; slots not listed
            are excluded entirely.

    Returns:
        A ``QRegion`` covering the emblem plus the visible slots' controls.
    """
    region = QRegion(emblem_rect)
    visible_set = set(visible)
    for slot_id, rects in card_controls.items():
        if slot_id not in visible_set:
            continue
        for rect in rects:
            region = region.united(rect)
    return region


def clamp_to_envelope(
    rect: QRect,
    screens: list[Tuple[int, int, int, int]],
    margin: int,
) -> QRect:
    """Clamp *rect*'s top-left so it still overlaps the screen envelope.

    The envelope is the bounding union of *screens* (each an ``(x, y, w, h)``
    tuple) inflated by *margin* on every side. Only the top-left is moved; the
    width and height are preserved. If *screens* is empty, *rect* is returned
    unchanged.

    Args:
        rect: the candidate window rect (screen coords).
        screens: screen geometries as ``(x, y, w, h)`` tuples.
        margin: pixels to inflate the envelope by on each side.

    Returns:
        A new ``QRect`` guaranteed to overlap the inflated envelope.
    """
    if not screens:
        return QRect(rect)

    env = QRect()
    for (x, y, w, h) in screens:
        r = QRect(x, y, w, h)
        env = r if env.isNull() else env.united(r)
    env = env.adjusted(-margin, -margin, margin, margin)

    width = rect.width()
    height = rect.height()

    # x range that keeps [x, x+width) overlapping [env.left, env.right].
    min_x = env.left() - width + 1
    max_x = env.right()
    new_x = min(max(rect.x(), min_x), max_x)

    min_y = env.top() - height + 1
    max_y = env.bottom()
    new_y = min(max(rect.y(), min_y), max_y)

    return QRect(new_x, new_y, width, height)
