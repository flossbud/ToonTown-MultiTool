"""Pure logic for click sync: aspect compatibility, coordinate mapping, the
per-slot state machine, and the gesture record. No X, no Qt: everything here
is unit-testable and shared by ClickSyncService.

Geometry tuples are (root_x, root_y, width, height) of a client window.
"""
from __future__ import annotations

from dataclasses import dataclass

ASPECT_TOLERANCE = 0.01

# UI slot states (per spec): off / armed / active / error
SLOT_COUNT = 4


def aspect_compatible(geoms: list[tuple[int, int, int, int]]) -> bool:
    """True when EVERY pair of geometries shares an aspect ratio within
    tolerance. Cross-product relative error avoids division by zero and
    scale dependence: |w1*h2 - w2*h1| / max(w1*h2, w2*h1) <= tol.
    All-pairs, not relative to one reference: the relation is not
    transitive at the tolerance boundary."""
    for g in geoms:
        if g[2] <= 0 or g[3] <= 0:
            return False
    for i in range(len(geoms)):
        for j in range(i + 1, len(geoms)):
            w1, h1 = geoms[i][2], geoms[i][3]
            w2, h2 = geoms[j][2], geoms[j][3]
            a, b = w1 * h2, w2 * h1
            if abs(a - b) / max(a, b) > ASPECT_TOLERANCE:
                return False
    return True


def map_point(src_geom: tuple[int, int, int, int],
              tgt_geom: tuple[int, int, int, int],
              root_x: int, root_y: int) -> tuple[int, int]:
    """Map a root-space point through the source window's relative space into
    the target's client space. Out-of-bounds points pass through unmodified
    (an outside release must keep its click-cancel semantics; never clamp).

    Precondition: src_geom has positive width/height — guaranteed because
    gestures only start while the group is active, which requires geometry
    that passed aspect_compatible (positive sizes).

    Quantization note: integer rounding means a point less than half a
    target pixel outside the source maps onto the target's edge pixel.
    Real cancel-releases land far outside, so this is accepted."""
    sx, sy, sw, sh = src_geom
    _, _, tw, th = tgt_geom
    rx = (root_x - sx) / sw
    ry = (root_y - sy) / sh
    return (round(rx * tw), round(ry * th))


def compute_slot_states(members: set[int],
                        usable: dict[int, bool],
                        compatible: bool) -> dict[int, str]:
    """Per-slot UI state. Group runs (all members 'active') only when every
    member is usable, there are >= 2, and all geometries are compatible.
    Any unusable member pauses the whole group (all-or-nothing in v1):
    the unusable slot shows 'error', usable members drop back to 'armed'.
    A geometry mismatch shows 'error' on every usable member; when both
    conditions hold (an unusable member AND mismatched usable members),
    mismatch wins for the usable members — they show 'error', not 'armed'.

    Preconditions: callers guarantee member slots are in range(SLOT_COUNT)
    (the UI has exactly SLOT_COUNT buttons), and `compatible` is computed
    over the USABLE members' geometries — vacuously True with fewer than
    two usable members."""
    states = {s: "off" for s in range(SLOT_COUNT)}
    usable_members = [s for s in members if usable.get(s)]
    group_active = (
        len(members) >= 2
        and len(usable_members) == len(members)
        and compatible
    )
    for s in members:
        if not usable.get(s):
            states[s] = "error"
        elif group_active:
            states[s] = "active"
        elif len(usable_members) >= 2 and not compatible:
            states[s] = "error"
        else:
            states[s] = "armed"
    return states


@dataclass(frozen=True)
class Gesture:
    """One in-flight button-1 gesture. Frozen at press: all motion/release
    mapping for the rest of the gesture uses this snapshot (spec: geometry
    and target XIDs are frozen at press). frozen=True enforces the
    field-level invariant; the targets dict itself is constructed once and
    never mutated."""
    source_slot: int
    source_geom: tuple[int, int, int, int]
    press_root: tuple[int, int]
    press_state: int
    press_time: int
    # slot -> (window_id, target_geom, (press_tx, press_ty))
    targets: dict[int, tuple[str, tuple[int, int, int, int], tuple[int, int]]]
