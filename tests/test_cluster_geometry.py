"""Tests for pure cluster geometry helpers (single-window cluster overlay).

These exercise QRect/QRegion math only - no widget state, fully offscreen.
QRegion lives in QtGui (not QtCore); its ops here do not require a running
QApplication, but a module-scoped fixture guarantees one exists in case a
backend variant needs it.
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QRegion

from utils.overlay.cluster_geometry import (
    clamp_to_envelope,
    cluster_bbox,
    envelope_for,
    input_union,
    map_host_point_to_window,
    map_host_rect_to_window,
    map_window_point_to_host,
    scaled_content_rect,
    window_rect_for,
)


@pytest.fixture(scope="module", autouse=True)
def qapp():
    """Ensure a QApplication exists for any QRegion op that needs one."""
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


# --------------------------------------------------------------------------- #
# cluster_bbox
# --------------------------------------------------------------------------- #
def test_cluster_bbox_unions_2x2_grid():
    # Four 40x30 cards laid out 2x2 with a 20px gap between them.
    rects = [
        QRect(0, 0, 40, 30),
        QRect(60, 0, 40, 30),
        QRect(0, 40, 40, 30),
        QRect(60, 40, 40, 30),
    ]
    assert cluster_bbox(rects) == QRect(0, 0, 100, 70)


def test_cluster_bbox_empty_is_null():
    bbox = cluster_bbox([])
    assert bbox.isNull()
    assert bbox == QRect()


# --------------------------------------------------------------------------- #
# window_rect_for
# --------------------------------------------------------------------------- #
def test_window_rect_for_centered_emblem_centers_bbox_on_anchor():
    # Emblem at the bbox center -> the bbox lands centered on the anchor.
    rect = window_rect_for(
        cluster_bbox_size=(100, 70),
        emblem_center_local=(50, 35),
        anchor=(500, 400),
    )
    assert rect == QRect(450, 365, 100, 70)
    # Emblem center (== bbox center here) sits exactly on the anchor.
    assert (rect.x() + 50, rect.y() + 35) == (500, 400)


def test_window_rect_for_noncentered_emblem_keeps_emblem_on_anchor():
    # Bug guard: emblem is NOT at the bbox center. A naive "center the bbox on
    # the anchor" placement would put top-left at (450,365) and the emblem at
    # (510,385) - which is wrong. The emblem center MUST land on the anchor.
    rect = window_rect_for(
        cluster_bbox_size=(100, 70),
        emblem_center_local=(60, 20),
        anchor=(500, 400),
    )
    # The window hugs the bbox exactly.
    assert rect.width() == 100
    assert rect.height() == 70
    assert rect == QRect(440, 380, 100, 70)
    # Emblem center (offset emblem_center_local from the subtree top-left,
    # which equals the window top-left) lands on anchor.
    assert (rect.x() + 60, rect.y() + 20) == (500, 400)


# --------------------------------------------------------------------------- #
# input_union
# --------------------------------------------------------------------------- #
def test_input_union_includes_emblem_and_visible_excludes_hidden():
    emblem = QRect(0, 0, 20, 20)
    card_controls = {
        0: [QRect(100, 100, 10, 10)],
        1: [QRect(200, 200, 10, 10)],
    }
    region = input_union(emblem, card_controls, visible={0})
    assert isinstance(region, QRegion)
    # Emblem is always in.
    assert region.contains(QPoint(5, 5))
    # Visible slot 0's control is in.
    assert region.contains(QPoint(105, 105))
    # Hidden slot 1's control is excluded.
    assert not region.contains(QPoint(205, 205))


def test_input_union_multiple_visible_and_multiple_controls_per_slot():
    emblem = QRect(0, 0, 20, 20)
    card_controls = {
        0: [QRect(100, 100, 10, 10), QRect(120, 100, 10, 10)],
        1: [QRect(200, 200, 10, 10)],
        2: [QRect(300, 300, 10, 10)],
    }
    region = input_union(emblem, card_controls, visible={0, 2})
    assert region.contains(QPoint(105, 105))  # slot 0, first control
    assert region.contains(QPoint(125, 105))  # slot 0, second control
    assert region.contains(QPoint(305, 305))  # slot 2
    assert not region.contains(QPoint(205, 205))  # slot 1 hidden


# --------------------------------------------------------------------------- #
# clamp_to_envelope
# --------------------------------------------------------------------------- #
def test_clamp_to_envelope_pulls_off_right_edge_back():
    screen = (0, 0, 1920, 1080)
    off = QRect(2500, 500, 100, 100)
    clamped = clamp_to_envelope(off, [screen], margin=0)
    # Size preserved.
    assert clamped.width() == 100
    assert clamped.height() == 100
    # Now overlaps the screen union.
    assert clamped.intersects(QRect(*screen))
    # It actually moved left.
    assert clamped.x() < off.x()


def test_clamp_to_envelope_noop_when_inside():
    screen = (0, 0, 1920, 1080)
    inside = QRect(100, 100, 100, 100)
    clamped = clamp_to_envelope(inside, [screen], margin=0)
    assert clamped == inside


def test_clamp_to_envelope_identity_with_empty_screens():
    rect = QRect(2500, 500, 100, 100)
    assert clamp_to_envelope(rect, [], margin=50) == rect


def test_clamp_to_envelope_pulls_off_left_edge_back():
    screen = (0, 0, 1920, 1080)
    off = QRect(-500, 500, 100, 100)
    clamped = clamp_to_envelope(off, [screen], margin=0)
    assert clamped.width() == 100 and clamped.height() == 100
    assert clamped.intersects(QRect(*screen))
    assert clamped.x() > off.x()


def test_cluster_bbox_does_not_alias_caller_input():
    # The single-rect path must return an INDEPENDENT QRect (pure helper); mutating
    # the result must not mutate the caller's input.
    src = QRect(1, 2, 3, 4)
    bbox = cluster_bbox([src])
    assert bbox == QRect(1, 2, 3, 4)
    bbox.moveTo(99, 99)
    assert src == QRect(1, 2, 3, 4)                       # input untouched


def test_clamp_to_envelope_pulls_off_top_and_bottom_back():
    screen = (0, 0, 1920, 1080)
    off_top = clamp_to_envelope(QRect(500, -500, 100, 100), [screen], margin=0)
    assert off_top.intersects(QRect(*screen)) and off_top.y() > -500
    off_bottom = clamp_to_envelope(QRect(500, 5000, 100, 100), [screen], margin=0)
    assert off_bottom.intersects(QRect(*screen)) and off_bottom.y() < 5000


def test_clamp_to_envelope_exact_boundary_keeps_one_px_overlap():
    # Just past the right edge -> clamped so exactly 1px overlaps (Qt right() is
    # inclusive); locks the off-by-one (+1) bound against regression.
    screen = (0, 0, 100, 100)            # env right/bottom inclusive = 99
    clamped = clamp_to_envelope(QRect(200, 10, 30, 30), [screen], margin=0)
    assert clamped.x() == 99             # first pixel sits on env.right()
    assert clamped.intersects(QRect(*screen))


def test_input_union_visible_slot_absent_from_controls_is_safe():
    # A slot in `visible` with no card_controls entry must NOT raise; region is
    # just the emblem.
    emblem = QRect(40, 40, 20, 20)
    region = input_union(emblem, {0: [QRect(0, 0, 10, 5)]}, visible={5})
    assert region.contains(QPoint(45, 45))       # emblem present
    assert not region.contains(QPoint(2, 2))     # slot 0 not visible -> excluded


# --------------------------------------------------------------------------- #
# envelope_for (fixed max-scale window)
# --------------------------------------------------------------------------- #
def test_envelope_for_integer_scale_is_exact():
    # 400x300 host, off-center emblem (110, 90), max scale 2.0: every extent
    # doubles exactly, pivot = scaled emblem offsets.
    (w, h), (px, py) = envelope_for((400, 300), (110, 90), 2.0)
    assert (w, h) == (800, 600)
    assert (px, py) == (220, 180)


def test_envelope_for_ceils_outward_never_clips():
    # Fractional extents must round UP: 1.75 * 110 = 192.5 -> 193, etc. The
    # envelope must CONTAIN the true scaled bbox at max scale on every side.
    (w, h), (px, py) = envelope_for((400, 300), (110, 90), 1.75)
    assert px >= 110 * 1.75 and py >= 90 * 1.75
    assert w - px >= (400 - 110) * 1.75
    assert h - py >= (300 - 90) * 1.75
    # And it is tight to within the 1px-per-side ceil.
    assert w <= 400 * 1.75 + 2 and h <= 300 * 1.75 + 2


def test_envelope_window_rect_composes_with_window_rect_for():
    # Placing the envelope via window_rect_for puts the PIVOT on the anchor.
    (size, pivot) = envelope_for((400, 300), (110, 90), 1.75)
    rect = window_rect_for(size, pivot, (1000, 700))
    assert (rect.x() + pivot[0], rect.y() + pivot[1]) == (1000, 700)
    assert (rect.width(), rect.height()) == size


# --------------------------------------------------------------------------- #
# map_host_rect_to_window / map_window_point_to_host
# --------------------------------------------------------------------------- #
def test_map_host_rect_identity_at_pivot_scale_one():
    # scale 1.0 with pivot == emblem center is the identity.
    r = map_host_rect_to_window(QRect(10, 20, 30, 40), (110, 90), (110, 90), 1.0)
    assert r == QRect(10, 20, 30, 40)


def test_map_host_rect_scales_about_emblem_center():
    # The emblem's own rect maps CENTERED on the pivot at every scale.
    emblem = QRect(60, 40, 100, 100)           # center (110, 90)
    for s in (0.5, 1.0, 1.5, 2.0):
        m = map_host_rect_to_window(emblem, (110, 90), (220, 180), s)
        cx = m.x() + m.width() / 2.0
        cy = m.y() + m.height() / 2.0
        # Outward rounding may shift the center by at most half a pixel.
        assert abs(cx - 220) <= 1.0 and abs(cy - 180) <= 1.0
        assert m.width() >= 100 * s - 1e-9     # never clips the true rect


def test_map_host_rect_rounds_outward():
    # A rect whose scaled edges are fractional must round outward (contain).
    r = map_host_rect_to_window(QRect(0, 0, 3, 3), (0, 0), (0, 0), 1.5)
    assert r == QRect(0, 0, 5, 5)              # 4.5 -> ceil 5
    r2 = map_host_rect_to_window(QRect(1, 1, 3, 3), (0, 0), (0, 0), 1.5)
    assert r2.x() == 1 and r2.y() == 1         # 1.5 -> floor 1
    assert r2.width() == 5                     # right 6.0 - floor(1.5) = 5


def test_map_window_point_round_trips_host_point():
    ec, pivot = (110, 90), (220, 180)
    for s in (0.5, 1.0, 1.75):
        for hx, hy in ((0, 0), (110, 90), (399, 299), (25, 250)):
            wr = map_host_rect_to_window(QRect(hx, hy, 1, 1), ec, pivot, s)
            bx, by = map_window_point_to_host(
                (wr.x() + wr.width() // 2, wr.y() + wr.height() // 2),
                ec, pivot, s)
            assert abs(bx - hx) <= 1 and abs(by - hy) <= 1


def test_map_window_point_nonpositive_scale_degrades_to_identity():
    assert map_window_point_to_host((10, 20), (0, 0), (0, 0), 0) == (10, 20)
    assert map_window_point_to_host((10, 20), (0, 0), (0, 0), -3) == (10, 20)


def test_map_host_point_identity_at_pivot_scale_one():
    assert map_host_point_to_window((10, 20), (110, 90), (110, 90), 1.0) == (10, 20)


def test_map_host_point_scales_about_emblem_center():
    # The emblem center itself always lands on the pivot; other points scale
    # their offset from it: window = pivot + (host - emblem_center) * s.
    ec, pivot = (110, 90), (220, 180)
    assert map_host_point_to_window(ec, ec, pivot, 1.75) == pivot
    assert map_host_point_to_window((110 + 40, 90 - 20), ec, pivot, 1.5) == (
        220 + 60, 180 - 30)


def test_map_host_point_inverts_map_window_point():
    ec, pivot = (110, 90), (220, 180)
    for s in (0.5, 1.0, 1.75):
        for hx, hy in ((0, 0), (110, 90), (399, 299), (25, 250)):
            wx, wy = map_host_point_to_window((hx, hy), ec, pivot, s)
            bx, by = map_window_point_to_host((wx, wy), ec, pivot, s)
            assert abs(bx - hx) <= 1 and abs(by - hy) <= 1


# --------------------------------------------------------------------------- #
# scaled_content_rect (move clamping operates on CONTENT, not the envelope)
# --------------------------------------------------------------------------- #
def test_scaled_content_rect_pins_emblem_center_on_anchor():
    r = scaled_content_rect((400, 300), (110, 90), (1000, 700), 1.0)
    assert r == QRect(1000 - 110, 700 - 90, 400, 300)


def test_scaled_content_rect_shrinks_with_scale_about_anchor():
    r = scaled_content_rect((400, 300), (110, 90), (1000, 700), 0.5)
    # Half-size content, emblem center still on the anchor.
    assert r.x() == 1000 - 55 and r.y() == 700 - 45
    assert r.width() == 200 and r.height() == 150


def test_scaled_content_rect_rounds_outward_on_fractional_scale():
    r = scaled_content_rect((401, 301), (110, 90), (0, 0), 1.75)
    # Contains the true rect: left/top floored, right/bottom ceiled.
    assert r.x() <= -110 * 1.75 and r.y() <= -90 * 1.75
    assert r.x() + r.width() >= (401 - 110) * 1.75
    assert r.y() + r.height() >= (301 - 90) * 1.75
