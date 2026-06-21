"""Pure 2x2 cell assignment for position-based card placement.

Given the on-screen centers of the detected game windows, assign each to a
distinct cluster cell (0=TL, 1=TR, 2=BL, 3=BR) that matches its quadrant, by
optimal matching to the ideal 2x2 grid over the windows' bounding box. Self
-relative (independent of absolute screen position / monitor), deterministic, and
Qt-free so it is unit-testable headless.
"""
from __future__ import annotations

from itertools import permutations

# Cell indices and their corner of the bounding box (the "ideal" point each cell
# pulls toward): TL=top-left, TR=top-right, BL=bottom-left, BR=bottom-right.
_NUM_CELLS = 4


def assign_window_cells(centers):
    """Assign each window center to a distinct 2x2 cell.

    centers: list of ``(cx, cy)`` window-center points, in any order.

    Returns a list of cell indices (0-3) aligned to the input order. At most four
    windows are placed; if more are given, the four nearest reading-order windows
    are placed and every extra gets ``-1`` (the caller orders those last). An empty
    input returns ``[]``. The function never raises.

    Matching: lay the ideal 2x2 grid over the bounding box of the placed centers
    (TL=(minx,miny), TR=(maxx,miny), BL=(minx,maxy), BR=(maxx,maxy)), then choose
    the injective window->cell assignment minimizing total squared distance. Ties
    (degenerate rows/columns, coincident points) break deterministically toward the
    top-left: the windows are pre-ordered by ``(cy, cx, index)`` and, among
    equal-cost assignments, the lexicographically smallest cell tuple wins. So a
    horizontal pair fills the top row, a vertical stack fills the left column, and a
    full 2x2 maps exactly.
    """
    n = len(centers)
    if n == 0:
        return []

    # Deterministic reading-order pre-sort drives the tie-break direction.
    order = sorted(range(n), key=lambda i: (centers[i][1], centers[i][0], i))
    placed = order[:_NUM_CELLS]
    pts = [centers[i] for i in placed]

    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)
    ideal = {
        0: (minx, miny),  # TL
        1: (maxx, miny),  # TR
        2: (minx, maxy),  # BL
        3: (maxx, maxy),  # BR
    }

    k = len(placed)
    best_key = None
    best_perm = None
    for perm in permutations(range(_NUM_CELLS), k):
        cost = 0
        for (px, py), cell in zip(pts, perm):
            ix, iy = ideal[cell]
            dx, dy = px - ix, py - iy
            cost += dx * dx + dy * dy
        key = (cost, perm)  # min cost, then lexicographically smallest cell tuple
        if best_key is None or key < best_key:
            best_key = key
            best_perm = perm

    cells = [-1] * n
    for placed_index, cell in zip(placed, best_perm):
        cells[placed_index] = cell
    return cells


def occupied_cells(slot_to_cell, window_count) -> frozenset[int]:
    """Cells (0-3) that currently hold a detected game window.

    ``slot_to_cell[i]`` is the 2x2 cell that slot i's content is routed to; the
    dense window list fills slots 0..window_count-1, so those slots' cells are the
    occupied ones. Combining the COUNT with the routing (rather than reading the
    routing alone) is load-bearing: detection can be disabled while a stale
    permutation lingers, so only the count tells us a cell is truly empty. Pure;
    total for a numeric ``window_count`` (clamps it into [0, len(slot_to_cell)]).
    Returns the SET of occupied cells, so two slots sharing a cell count once
    (the real routing is always a bijection, so that never happens in practice).
    """
    n = max(0, min(int(window_count), len(slot_to_cell)))
    return frozenset(slot_to_cell[i] for i in range(n))
