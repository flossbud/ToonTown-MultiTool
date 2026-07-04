"""Frame-paced ghost rendering (the smoothness fix, live 2026-07-04).

The service emits a ghost point per CAPTURED MOTION EVENT (up to the mouse's
polling rate, 1000Hz on gaming mice); rendering per emit kept the GUI thread
saturated and gloves stuttered. A real cursor is smooth because the display
samples only the LATEST position once per frame - so _on_pointer_event is a
near-free sampler (newest point per slot) and the frame driver renders dirty
slots at frame cadence (~4ms). The FIRST event after idle renders
synchronously (instant appearance); the driver stops itself when the stream
ends. Backlog is impossible by construction at any polling rate.

The sibling suites (test_ghost_cursors*, test_ghost_echo,
test_ghost_occlusion_gate) assert synchronously after each emit and flush
via their autouse _sync_ghost_frames fixture; THIS suite pins the paced
path itself.
"""
import pytest
from PySide6.QtCore import QRect
from PySide6.QtGui import QRegion

from tabs.multitoon._ghost_cursors import (
    CURSOR_SIZE,
    HOTSPOT,
    GhostCursorController,
    _region_from_inputs,
    _scan_region_inputs,
    _visible_glove_region,
)

GAME = 111
FOREIGN = 333
OWN_PID = 4242
IDENT = lambda x, y: (x, y)  # noqa: E731


@pytest.fixture
def ctl(qapp):
    c = GhostCursorController(service=None, settings_manager=None)
    assert c._disabled_reason is None, c._disabled_reason
    c._occlusion_gated = False        # pacing tests; gate has its own suite
    yield c
    c._hide_all()
    for ov in c._overlays.values():
        ov.deleteLater()


def _pos(ctl, slot):
    ov = ctl._overlays[slot]
    return (ov.x() + HOTSPOT[0], ov.y() + HOTSPOT[1])


def test_first_event_after_idle_renders_synchronously(ctl):
    ctl._on_pointer_event(("motion", [(0, 100, 100)]))
    assert ctl._overlays[0].isVisible()
    assert _pos(ctl, 0) == (100, 100)          # rendered NOW, not deferred
    assert ctl._frame_timer is not None and ctl._frame_timer.isActive()


def test_stream_coalesces_to_latest_point(ctl):
    ctl._on_pointer_event(("motion", [(0, 100, 100)]))   # sync render
    # Driver active: these only sample (no render until the next tick).
    ctl._on_pointer_event(("motion", [(0, 200, 200)]))
    ctl._on_pointer_event(("motion", [(0, 300, 300)]))
    assert _pos(ctl, 0) == (100, 100)
    assert ctl._pending_points[0] == (300, 300)
    ctl._frame_tick()
    assert _pos(ctl, 0) == (300, 300)          # newest wins; 200 never drawn


def test_batch_samples_every_slot(ctl):
    ctl._on_pointer_event(("motion", [(0, 10, 10), (1, 20, 20)]))
    assert _pos(ctl, 0) == (10, 10)
    assert _pos(ctl, 1) == (20, 20)


def test_driver_stops_when_stream_ends(ctl):
    ctl._on_pointer_event(("motion", [(0, 100, 100)]))
    assert ctl._frame_timer.isActive()
    ctl._frame_tick()                          # nothing pending -> stops
    assert not ctl._frame_timer.isActive()
    # A fresh event after idle renders synchronously again.
    ctl._on_pointer_event(("motion", [(0, 150, 150)]))
    assert _pos(ctl, 0) == (150, 150)


def test_hide_all_clears_pending_and_stops_driver(ctl):
    ctl._on_pointer_event(("motion", [(0, 100, 100)]))
    ctl._on_pointer_event(("motion", [(0, 200, 200)]))   # sampled
    ctl._hide_all()
    assert ctl._pending_points == {}
    assert not ctl._frame_timer.isActive()
    assert not ctl._overlays[0].isVisible()


def test_focus_suppression_applies_at_render_time(ctl):
    ctl._slot_window_resolver = lambda slot: str(GAME)
    ctl._on_pointer_event(("motion", [(0, 100, 100)]))
    ctl.set_focused_window(str(GAME))          # focus lands mid-stream
    ctl._on_pointer_event(("motion", [(0, 200, 200)]))
    ctl._frame_tick()
    # The sampled point must not render onto the now-focused window.
    assert not ctl._overlays[0].isVisible()


# ── region-inputs cache: one snapshot scan per snapshot identity ─────────────

def _gated(ctl, snap_holder):
    ctl._occlusion_gated = True
    ctl._own_pid = OWN_PID
    ctl._to_logical = IDENT
    ctl._slot_window_resolver = lambda slot: str(GAME)
    ctl._zorder_probe = lambda: snap_holder["snap"]
    return ctl


def test_region_inputs_scanned_once_per_snapshot_identity(ctl, monkeypatch):
    from tabs.multitoon import _ghost_cursors as gc
    holder = {"snap": [(GAME, (0, 0, 1600, 1200), 777)]}
    _gated(ctl, holder)
    scans = []
    real_scan = gc._scan_region_inputs
    monkeypatch.setattr(
        gc, "_scan_region_inputs",
        lambda *a: scans.append(1) or real_scan(*a))
    ctl._render_point(0, 100, 100)
    ctl._render_point(0, 200, 200)             # same snapshot object
    assert len(scans) == 1
    holder["snap"] = [(GAME, (0, 0, 1600, 1200), 777)]  # NEW object
    ctl._render_point(0, 300, 300)
    assert len(scans) == 2


def test_cached_inputs_still_mask_correctly_per_position(ctl):
    holder = {"snap": [(FOREIGN, (116, 0, 900, 600), 555),
                       (GAME, (0, 0, 1600, 1200), 777)]}
    _gated(ctl, holder)
    gx, gy = 100 - HOTSPOT[0], 100 - HOTSPOT[1]
    holder["snap"] = [(FOREIGN, (gx + 16, 0, 900, 600), 555),
                      (GAME, (0, 0, 1600, 1200), 777)]
    ctl._render_point(0, 100, 100)
    ov = ctl._overlays[0]
    assert ov._occ_region == QRegion(QRect(0, 0, 16, CURSOR_SIZE))
    # Second position against the SAME snapshot: mask follows the glove.
    ctl._render_point(0, 100 - 8, 100)
    assert ov._occ_region == QRegion(QRect(0, 0, 24, CURSOR_SIZE))


# ── split helpers stay equivalent to the one-shot region function ────────────

def test_scan_plus_build_equivalent_to_visible_glove_region():
    snap = [(FOREIGN, (116, 0, 900, 600), 555),
            (GAME, (0, 0, 800, 600), 777)]
    glove = QRect(100, 100, CURSOR_SIZE, CURSOR_SIZE)
    inputs = _scan_region_inputs(GAME, snap, OWN_PID, IDENT)
    assert _region_from_inputs(glove, inputs) == _visible_glove_region(
        glove, GAME, snap, OWN_PID, IDENT)


def test_scan_returns_none_when_game_absent_and_build_yields_empty():
    snap = [(FOREIGN, (0, 0, 900, 600), 555)]
    assert _scan_region_inputs(GAME, snap, OWN_PID, IDENT) is None
    glove = QRect(100, 100, CURSOR_SIZE, CURSOR_SIZE)
    assert _region_from_inputs(glove, None).isEmpty()


def test_non_intersecting_occluder_skip_matches_full_subtract():
    # The build path skips occluders that do not touch the glove; the result
    # must equal the naive subtract-everything region.
    snap = [(FOREIGN, (5000, 5000, 5100, 5100), 555),   # far away
            (444, (116, 0, 900, 600), 666),             # carves right half
            (GAME, (0, 0, 1600, 1200), 777)]
    glove = QRect(100, 100, CURSOR_SIZE, CURSOR_SIZE)
    assert _visible_glove_region(glove, GAME, snap, OWN_PID, IDENT) == \
        QRegion(QRect(0, 0, 16, CURSOR_SIZE))
