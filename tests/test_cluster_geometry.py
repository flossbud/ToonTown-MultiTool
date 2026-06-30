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
    input_union,
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
        radial_open=False,
        dim_extent=(0, 0),
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
        radial_open=False,
        dim_extent=(0, 0),
    )
    # radial closed -> window hugs the bbox exactly.
    assert rect.width() == 100
    assert rect.height() == 70
    assert rect == QRect(440, 380, 100, 70)
    # Emblem center (offset emblem_center_local from the subtree top-left,
    # which equals the window top-left when radial is closed) lands on anchor.
    assert (rect.x() + 60, rect.y() + 20) == (500, 400)


def test_window_rect_for_radial_open_grows_to_dim_but_keeps_emblem_on_anchor():
    # Dim canvas (240x240, emblem-centered) is larger than the bbox (100x70).
    # The window must grow to contain the dim, yet the emblem center stays put.
    dim = (240, 240)
    ecx, ecy = 50, 35
    rect = window_rect_for(
        cluster_bbox_size=(100, 70),
        emblem_center_local=(ecx, ecy),
        anchor=(500, 400),
        radial_open=True,
        dim_extent=dim,
    )
    # Grows to at least the dim extent.
    assert rect.width() >= dim[0]
    assert rect.height() >= dim[1]
    assert rect == QRect(380, 280, 240, 240)
    # Emblem center offset from the window top-left is max(ex, dw//2),
    # max(ey, dh//2) - derived from the documented contract, not internals.
    lx = max(ecx, dim[0] // 2)
    ty = max(ecy, dim[1] // 2)
    assert (rect.x() + lx, rect.y() + ty) == (500, 400)


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
