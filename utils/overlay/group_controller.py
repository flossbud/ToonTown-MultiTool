"""Surface-state model and pinwheel layout geometry for the transparent-mode overlay.

This module is PURE geometry + state: no Qt widgets, no QApplication, no
controller logic (that is Task 3.2).  PySide6.QtCore (QRect) is importable
headless without a running QApplication.

Emblem convention in SurfaceState
----------------------------------
Cards use surface_id 0-3 (matching the four pinwheel slots).
The emblem uses surface_id=-1 (a sentinel; callers must not depend on the
specific value) plus is_emblem=True.  Always check is_emblem, never the
sentinel value, when branching on emblem vs card.

Controller integration note (Task 3.2 / 4.2 - NOT implemented here)
----------------------------------------------------------------------
The controller (Task 3.2+) will reconcile each surface's final QRect with the
card's ACTUAL scaled sizeHint, which may differ from card_w*scale by rounding.
pinwheel_rects() provides the OFFSET geometry only; the controller owns the
size-reconcile step. Specifically: CardMetrics uses ``round(base * scale)``
while this function uses ``int(base * scale)`` (matching the spike), so for some
scales (e.g. 0.8, 1.3) the sizes differ by 1px. The controller resolves this by
reading ``sizeHint()`` from the real card widget (Task 4.2), NOT by recomputing
sizes here. The controller sources card_w/card_h from the live card's sizeHint
and the inter-corner gap (spike GAP=24) + emblem (CardMetrics.emblem=156) as the
base inputs to this function.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Union

from PySide6.QtCore import QRect

from utils.overlay.surface import ShapeMode


# ---------------------------------------------------------------------------
# Slot -> cutout-corner mapping
# ---------------------------------------------------------------------------
# Which corner of each card faces the group center (gets the pinwheel bite).
# Matches scripts/transparent_multiwindow_spike.py Group.__init__ and
# _CFG in tabs/multitoon/_compact_layout.py, and spec section 7.
SLOT_CUTOUTS: dict[int, str] = {
    0: "br",   # top-left quadrant     -> bite bottom-right toward center
    1: "bl",   # top-right quadrant    -> bite bottom-left toward center
    2: "tr",   # bottom-left quadrant  -> bite top-right toward center
    3: "tl",   # bottom-right quadrant -> bite top-left toward center
}


# ---------------------------------------------------------------------------
# SurfaceState dataclass
# ---------------------------------------------------------------------------
@dataclass
class SurfaceState:
    """Per-surface state for one overlay window (a card or the emblem).

    v1 invariants
    -------------
    - attached is always True (all four cards + emblem form one cluster).
    - group_id is always 0 (single group).
    - shape_mode is PINWHEEL_BITE for cards; not meaningful for the emblem.

    v2 extension path
    -----------------
    Setting attached=False and shape_mode=ROUNDED_RECT marks a card as
    free-floating.  No structural change needed here; it is a pure state
    transition the controller (Task 3.2+) reconciles into new geometry.

    Emblem convention
    -----------------
    Cards:  surface_id in {0, 1, 2, 3}, is_emblem=False.
    Emblem: surface_id=-1 (sentinel, do not rely on the value), is_emblem=True.
    """

    surface_id: int
    is_emblem: bool = False
    group_id: int = 0
    attached: bool = True
    anchor: tuple[int, int] = (0, 0)
    scale: float = 1.0
    shape_mode: ShapeMode = ShapeMode.PINWHEEL_BITE

    def __post_init__(self) -> None:
        # The two emblem discriminators must agree (callers branch on is_emblem;
        # keep surface_id in sync so the sentinel can never contradict the flag).
        if self.is_emblem and self.surface_id != -1:
            raise ValueError("emblem SurfaceState must use surface_id=-1")
        if not self.is_emblem and self.surface_id not in (0, 1, 2, 3):
            raise ValueError("card SurfaceState surface_id must be a slot 0-3")


# ---------------------------------------------------------------------------
# Return type alias for pinwheel_rects
# ---------------------------------------------------------------------------
# Keys: int (0-3) for card slots, or str "emblem" for the emblem window.
PinwheelRects = dict[Union[int, str], QRect]


# ---------------------------------------------------------------------------
# Pinwheel layout function
# ---------------------------------------------------------------------------
def pinwheel_rects(
    anchor: tuple[int, int],
    scale: float,
    card_w: int,
    card_h: int,
    emblem: int,
    gap: int,
) -> PinwheelRects:
    """Compute the screen-space QRect for each card slot and the emblem.

    This is the PROVEN spike formula from ``Group.apply()`` in
    ``scripts/transparent_multiwindow_spike.py`` (lines 208-224), extracted
    verbatim as a pure function.

    Parameters
    ----------
    anchor:
        ``(cx, cy)`` screen coordinates of the emblem CENTER / group pivot.
    scale:
        Overlay zoom factor (1.0 = base size). Applied internally to all base
        dimensions before computing positions (exactly as the spike does:
        ``cw = int(card_w * scale)``, etc.).
    card_w, card_h:
        BASE (scale-1.0) card dimensions in pixels.
    emblem:
        BASE (scale-1.0) emblem disc diameter in pixels.
    gap:
        BASE (scale-1.0) gap between each card's inner corner and the group
        center in pixels.

    Returns
    -------
    dict mapping:
        ``0, 1, 2, 3`` -> QRect for each card slot window (top-left origin).
        ``"emblem"``    -> QRect for the emblem window (centered on anchor).

    Slot layout (matches spike and ``_CFG`` in tabs/multitoon/_compact_layout.py):

    ====  =====================  =============
    Slot  Screen quadrant        Bite corner
    ====  =====================  =============
    0     top-left               br (bottom-right toward center)
    1     top-right              bl (bottom-left toward center)
    2     bottom-left            tr (top-right toward center)
    3     bottom-right           tl (top-left toward center)
    ====  =====================  =============

    See also ``SLOT_CUTOUTS`` for the slot -> bite-corner lookup table.
    """
    cx, cy = anchor

    # Scale all base dimensions (verbatim spike: int(X * s))
    cw: int = int(card_w * scale)
    ch: int = int(card_h * scale)
    em: int = int(emblem * scale)
    g: int = int(gap * scale)

    # Card top-left positions (spike formula, verbatim from Group.apply())
    card_origins = [
        (cx - g - cw, cy - g - ch),   # slot 0: top-left quadrant,     bite br
        (cx + g,      cy - g - ch),   # slot 1: top-right quadrant,    bite bl
        (cx - g - cw, cy + g),        # slot 2: bottom-left quadrant,  bite tr
        (cx + g,      cy + g),        # slot 3: bottom-right quadrant, bite tl
    ]

    result: PinwheelRects = {}
    for slot, (x, y) in enumerate(card_origins):
        result[slot] = QRect(x, y, cw, ch)

    # Emblem: centered on anchor (spike: emblem.move(cx - em // 2, cy - em // 2))
    result["emblem"] = QRect(cx - em // 2, cy - em // 2, em, em)

    return result
