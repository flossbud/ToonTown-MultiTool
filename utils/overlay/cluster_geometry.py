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
"""
from __future__ import annotations

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
    radial_open: bool,
    dim_extent: Tuple[int, int],
) -> QRect:
    """Compute the SCREEN rect for the single cluster window.

    The window is sized and placed so the emblem center sits exactly on
    *anchor*. Relative to the emblem center the cluster subtree extends
    ``left=ex``, ``right=w-ex``, ``top=ey``, ``bottom=h-ey``. When *radial_open*
    the emblem-centered dim/radial canvas adds ``dw/2`` on each horizontal side
    and ``dh/2`` on each vertical side. The window must contain BOTH, so each
    side extent is the max of the two demands.

    Args:
        cluster_bbox_size: ``(w, h)`` of the cluster subtree.
        emblem_center_local: ``(ex, ey)`` emblem center within the subtree
            (top-left origin).
        anchor: ``(ax, ay)`` screen point the emblem center must occupy.
        radial_open: whether the radial menu / dim canvas is showing.
        dim_extent: ``(dw, dh)`` of the emblem-centered dim canvas (only used
            when *radial_open*).

    Returns:
        The screen ``QRect`` for the window. In every case
        ``(rect.x() + Lx, rect.y() + Ty) == anchor`` where ``Lx``/``Ty`` are the
        left/top extents below.
    """
    w, h = cluster_bbox_size
    ex, ey = emblem_center_local
    ax, ay = anchor
    dw, dh = dim_extent

    # CEIL the half-extent ((dw+1)//2) so an ODD dim canvas is fully contained
    # (left+right >= dw); flooring (dw//2) would under-size the window by 1px and
    # clip the emblem-centered dim. The emblem-center invariant is unaffected
    # (the same `left`/`top` are used for both sizing and positioning).
    half_w = (dw + 1) // 2 if radial_open else 0
    half_h = (dh + 1) // 2 if radial_open else 0

    left = max(ex, half_w)
    right = max(w - ex, half_w)
    top = max(ey, half_h)
    bottom = max(h - ey, half_h)

    width = left + right
    height = top + bottom

    return QRect(ax - left, ay - top, width, height)


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
