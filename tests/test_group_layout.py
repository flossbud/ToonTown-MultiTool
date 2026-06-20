"""Pure-geometry tests for utils/overlay/group_controller.py.

No QApplication needed: only PySide6.QtCore (QRect) and plain Python dataclasses
are exercised here.  The conftest session fixture provides a QApplication so that
importing PySide6.QtWidgets (via surface.py) does not warn, but none of these
tests create or show any widget.

Run:
    TTMT_NO_VENV_REEXEC=1 ./venv/bin/python -m pytest tests/test_group_layout.py -q
or with explicit offscreen (harmless, no difference for pure tests):
    TTMT_NO_VENV_REEXEC=1 QT_QPA_PLATFORM=offscreen ./venv/bin/python -m pytest tests/test_group_layout.py -q
"""
import dataclasses

import pytest
from PySide6.QtCore import QRect

from utils.overlay.group_controller import (
    SLOT_CUTOUTS,
    SurfaceState,
    pinwheel_rects,
)
from utils.overlay.surface import ShapeMode


# ---------------------------------------------------------------------------
# Shared base parameters (mirror the spike's canonical values)
# ---------------------------------------------------------------------------
ANCHOR = (1000, 800)
SCALE = 1.0
CARD_W, CARD_H = 300, 232
EMBLEM = 156
GAP = 24


def _rects(scale: float = SCALE) -> dict:
    return pinwheel_rects(ANCHOR, scale, CARD_W, CARD_H, EMBLEM, GAP)


# Physical (non-Qt-off-by-one) right/bottom boundaries
def _right(r: QRect) -> int:
    return r.x() + r.width()


def _bottom(r: QRect) -> int:
    return r.y() + r.height()


def _phys_corners(r: QRect) -> dict[str, tuple[int, int]]:
    """Physical corner coordinates (no Qt QRect.right() off-by-one)."""
    return {
        "tl": (r.x(), r.y()),
        "tr": (_right(r), r.y()),
        "bl": (r.x(), _bottom(r)),
        "br": (_right(r), _bottom(r)),
    }


def _manhattan(p1: tuple[int, int], p2: tuple[int, int]) -> int:
    return abs(p1[0] - p2[0]) + abs(p1[1] - p2[1])


# ---------------------------------------------------------------------------
# pinwheel_rects: return-value shape
# ---------------------------------------------------------------------------
class TestReturnShape:
    def test_keys_are_0_1_2_3_and_emblem(self):
        assert set(_rects().keys()) == {0, 1, 2, 3, "emblem"}

    def test_all_values_are_qrect(self):
        for v in _rects().values():
            assert isinstance(v, QRect)

    def test_card_size_at_scale_1(self):
        r = _rects()
        for slot in range(4):
            assert r[slot].width() == CARD_W
            assert r[slot].height() == CARD_H

    def test_emblem_size_at_scale_1(self):
        r = _rects()
        assert r["emblem"].width() == EMBLEM
        assert r["emblem"].height() == EMBLEM


# ---------------------------------------------------------------------------
# Emblem centering
# ---------------------------------------------------------------------------
class TestEmblemCentering:
    def test_emblem_centered_on_anchor(self):
        """Emblem center should land on the anchor (within 1px for int rounding)."""
        r = _rects()
        em = r["emblem"]
        cx, cy = ANCHOR
        # Physical center: top-left + width/2, top-left + height/2
        phys_cx = em.x() + em.width() // 2
        phys_cy = em.y() + em.height() // 2
        assert abs(phys_cx - cx) <= 1
        assert abs(phys_cy - cy) <= 1


# ---------------------------------------------------------------------------
# Quadrant placement
# ---------------------------------------------------------------------------
class TestQuadrantPlacement:
    def test_slot0_up_and_left_of_anchor(self):
        r = _rects()
        cx, cy = ANCHOR
        s0 = r[0]
        assert _right(s0) <= cx, "slot 0 right edge should be left of anchor"
        assert _bottom(s0) <= cy, "slot 0 bottom edge should be above anchor"

    def test_slot1_up_and_right_of_anchor(self):
        r = _rects()
        cx, cy = ANCHOR
        s1 = r[1]
        assert s1.x() >= cx, "slot 1 left edge should be right of anchor"
        assert _bottom(s1) <= cy, "slot 1 bottom edge should be above anchor"

    def test_slot2_down_and_left_of_anchor(self):
        r = _rects()
        cx, cy = ANCHOR
        s2 = r[2]
        assert _right(s2) <= cx, "slot 2 right edge should be left of anchor"
        assert s2.y() >= cy, "slot 2 top edge should be below anchor"

    def test_slot3_down_and_right_of_anchor(self):
        r = _rects()
        cx, cy = ANCHOR
        s3 = r[3]
        assert s3.x() >= cx, "slot 3 left edge should be right of anchor"
        assert s3.y() >= cy, "slot 3 top edge should be below anchor"


# ---------------------------------------------------------------------------
# Symmetry
# ---------------------------------------------------------------------------
class TestSymmetry:
    def test_slot0_slot3_mirror_about_anchor(self):
        """slot 0 (top-left) and slot 3 (bottom-right) are mirror images."""
        r = _rects()
        cx, cy = ANCHOR
        s0, s3 = r[0], r[3]
        # Horizontal: gap from anchor to slot-0 right edge == gap from anchor to slot-3 left edge
        assert (cx - _right(s0)) == (s3.x() - cx)
        # Vertical: gap from anchor to slot-0 bottom == gap from anchor to slot-3 top
        assert (cy - _bottom(s0)) == (s3.y() - cy)

    def test_slot1_slot2_mirror_about_anchor(self):
        """slot 1 (top-right) and slot 2 (bottom-left) are mirror images."""
        r = _rects()
        cx, cy = ANCHOR
        s1, s2 = r[1], r[2]
        # Horizontal: gap from anchor to slot-1 left edge == gap from anchor to slot-2 right edge
        assert (s1.x() - cx) == (cx - _right(s2))
        # Vertical: gap from anchor to slot-1 bottom == gap from anchor to slot-2 top
        assert (cy - _bottom(s1)) == (s2.y() - cy)


# ---------------------------------------------------------------------------
# Bite corner: the corner facing the center must be the nearest corner
# ---------------------------------------------------------------------------
class TestBiteCornerFacesCenter:
    def _assert_nearest(self, slot: int, bite: str) -> None:
        r = _rects()
        anchor = ANCHOR
        c = _phys_corners(r[slot])
        bite_dist = _manhattan(c[bite], anchor)
        others = {k: _manhattan(v, anchor) for k, v in c.items() if k != bite}
        assert all(
            bite_dist < d for d in others.values()
        ), (
            f"slot {slot} bite corner '{bite}' (dist={bite_dist}) "
            f"is not the nearest corner to anchor; others: {others}"
        )

    def test_slot0_bite_br(self):
        self._assert_nearest(0, "br")

    def test_slot1_bite_bl(self):
        self._assert_nearest(1, "bl")

    def test_slot2_bite_tr(self):
        self._assert_nearest(2, "tr")

    def test_slot3_bite_tl(self):
        self._assert_nearest(3, "tl")


# ---------------------------------------------------------------------------
# Scale linearity
# ---------------------------------------------------------------------------
class TestScaleLinearity:
    def test_card_sizes_double_at_scale_2(self):
        r1 = _rects(scale=1.0)
        r2 = _rects(scale=2.0)
        for slot in range(4):
            assert r2[slot].width() == pytest.approx(r1[slot].width() * 2, abs=1)
            assert r2[slot].height() == pytest.approx(r1[slot].height() * 2, abs=1)

    def test_emblem_size_doubles_at_scale_2(self):
        r1 = _rects(scale=1.0)
        r2 = _rects(scale=2.0)
        assert r2["emblem"].width() == pytest.approx(r1["emblem"].width() * 2, abs=1)

    def test_offsets_from_anchor_double_at_scale_2(self):
        """Physical center-of-card offsets from the anchor scale linearly."""
        r1 = _rects(scale=1.0)
        r2 = _rects(scale=2.0)
        cx, cy = ANCHOR
        for slot in range(4):
            # Physical center (using width//2 to stay int-consistent)
            pc1x = r1[slot].x() + r1[slot].width() // 2
            pc1y = r1[slot].y() + r1[slot].height() // 2
            pc2x = r2[slot].x() + r2[slot].width() // 2
            pc2y = r2[slot].y() + r2[slot].height() // 2
            dx1, dy1 = pc1x - cx, pc1y - cy
            dx2, dy2 = pc2x - cx, pc2y - cy
            assert dx2 == pytest.approx(dx1 * 2, abs=1), (
                f"slot {slot} horizontal offset not linear: {dx2} vs {dx1 * 2}"
            )
            assert dy2 == pytest.approx(dy1 * 2, abs=1), (
                f"slot {slot} vertical offset not linear: {dy2} vs {dy1 * 2}"
            )


# ---------------------------------------------------------------------------
# SLOT_CUTOUTS table
# ---------------------------------------------------------------------------
class TestSlotCutoutsTable:
    def test_covers_all_four_slots(self):
        assert set(SLOT_CUTOUTS.keys()) == {0, 1, 2, 3}

    def test_all_values_are_valid_corner_names(self):
        valid = {"tl", "tr", "bl", "br"}
        assert all(v in valid for v in SLOT_CUTOUTS.values())

    def test_matches_spike_and_compact_cfg(self):
        """Spot-check against the spike comments and _CFG in _compact_layout.py."""
        assert SLOT_CUTOUTS[0] == "br"   # top-left quadrant
        assert SLOT_CUTOUTS[1] == "bl"   # top-right quadrant
        assert SLOT_CUTOUTS[2] == "tr"   # bottom-left quadrant
        assert SLOT_CUTOUTS[3] == "tl"   # bottom-right quadrant

    def test_bite_corners_match_pinwheel_rects_nearest_corner(self):
        """SLOT_CUTOUTS[slot] should agree with the nearest-corner test."""
        r = _rects()
        for slot, bite in SLOT_CUTOUTS.items():
            c = _phys_corners(r[slot])
            bite_dist = _manhattan(c[bite], ANCHOR)
            others = {k: v for k, v in c.items() if k != bite}
            assert all(bite_dist < _manhattan(v, ANCHOR) for v in others.values())


# ---------------------------------------------------------------------------
# SurfaceState dataclass
# ---------------------------------------------------------------------------
class TestSurfaceState:
    def test_is_a_plain_dataclass(self):
        assert dataclasses.is_dataclass(SurfaceState)

    def test_card_defaults(self):
        s = SurfaceState(surface_id=0)
        assert s.surface_id == 0
        assert s.is_emblem is False
        assert s.group_id == 0
        assert s.attached is True
        assert s.anchor == (0, 0)
        assert s.scale == 1.0
        assert s.shape_mode is ShapeMode.PINWHEEL_BITE

    def test_emblem_convention(self):
        s = SurfaceState(surface_id=-1, is_emblem=True)
        assert s.is_emblem is True
        # surface_id is -1 by convention when is_emblem=True; callers check is_emblem
        assert s.surface_id == -1

    def test_all_slots_constructable(self):
        for i in range(4):
            s = SurfaceState(surface_id=i)
            assert s.surface_id == i

    def test_fields_are_mutable_for_v2_transition(self):
        """All fields must be settable: v2 detach is a state change, not a rewrite."""
        s = SurfaceState(surface_id=2)
        s.attached = False
        s.shape_mode = ShapeMode.ROUNDED_RECT
        s.scale = 1.5
        s.anchor = (500, 400)
        assert s.attached is False
        assert s.shape_mode is ShapeMode.ROUNDED_RECT
        assert s.scale == 1.5
        assert s.anchor == (500, 400)

    def test_shape_mode_enum_values_exist(self):
        """Both ShapeMode values referenced by the spec are importable."""
        assert ShapeMode.PINWHEEL_BITE is not None
        assert ShapeMode.ROUNDED_RECT is not None


# ---------------------------------------------------------------------------
# Boundary scales (the real clamped operating envelope: 0.5 and 1.75)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("scale", [0.5, 1.75])
def test_pinwheel_rects_at_clamp_boundaries(scale):
    cx, cy = ANCHOR
    r = _rects(scale=scale)
    em = int(EMBLEM * scale)
    cw, ch = int(CARD_W * scale), int(CARD_H * scale)
    # Emblem centered on the anchor, sized int(base*scale).
    assert r["emblem"] == QRect(cx - em // 2, cy - em // 2, em, em)
    # Card sizes are int(base*scale).
    assert r[0].width() == cw and r[0].height() == ch
    # Slot 0 stays up-and-left of the anchor; slot 3 down-and-right.
    assert _right(r[0]) <= cx and (r[0].y() + r[0].height()) <= cy
    assert r[3].x() >= cx and r[3].y() >= cy


# ---------------------------------------------------------------------------
# SurfaceState emblem/surface_id consistency (the v2 state model invariant)
# ---------------------------------------------------------------------------
def test_surface_state_valid_combinations():
    SurfaceState(surface_id=-1, is_emblem=True)        # emblem
    for slot in range(4):
        SurfaceState(surface_id=slot)                  # cards (is_emblem default False)


def test_surface_state_rejects_contradictory_emblem_flag():
    with pytest.raises(ValueError):
        SurfaceState(surface_id=0, is_emblem=True)     # card slot but flagged emblem
    with pytest.raises(ValueError):
        SurfaceState(surface_id=-1, is_emblem=False)   # sentinel id but not flagged emblem
    with pytest.raises(ValueError):
        SurfaceState(surface_id=5)                      # out-of-range card slot
