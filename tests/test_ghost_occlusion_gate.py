"""Win32 ghost-cursor occlusion gate, region model (offscreen, probes injected).

On Windows the gloves are unconfined always-on-top floats; the gate clips
each glove to its game window's VISIBLE surface - (glove ∩ game rect) minus
every foreign window above the game in z-order - applied as a window mask so
the sprite slides UNDER an occluder's edge pixel by pixel (the X11 confined
look). A fully carved glove hides; the periodic sweep restores it when the
occluder moves away. The z-order probe is an instance attribute, faked here.
"""
import pytest
from PySide6.QtCore import QRect
from PySide6.QtGui import QRegion
from PySide6.QtWidgets import QApplication

from tabs.multitoon._ghost_cursors import (
    CURSOR_SIZE,
    HOTSPOT,
    GhostCursorController,
    _visible_glove_region,
)

GAME = 111
OTHER_GAME = 222
FOREIGN = 333
APP_WIN = 444
OWN_PID = 4242
IDENT = lambda x, y: (x, y)  # noqa: E731  logical == raw in these tests


# ---------------------------------------------------------------------------
# _visible_glove_region (pure)
# ---------------------------------------------------------------------------

def _glove(x=100, y=100):
    return QRect(x, y, CURSOR_SIZE, CURSOR_SIZE)


def test_region_full_over_uncovered_game():
    snap = [(GAME, (0, 0, 800, 600), 777)]
    r = _visible_glove_region(_glove(), GAME, snap, OWN_PID, IDENT)
    assert r == QRegion(QRect(0, 0, CURSOR_SIZE, CURSOR_SIZE))


def test_region_carved_by_overlapping_occluder():
    # Explorer covers the RIGHT half of the glove (x >= 116 in globals).
    snap = [(FOREIGN, (116, 0, 900, 600), 555),
            (GAME, (0, 0, 800, 600), 777)]
    r = _visible_glove_region(_glove(), GAME, snap, OWN_PID, IDENT)
    assert r == QRegion(QRect(0, 0, 16, CURSOR_SIZE))   # left half remains


def test_region_empty_when_fully_covered():
    snap = [(FOREIGN, (0, 0, 900, 600), 555),
            (GAME, (0, 0, 800, 600), 777)]
    r = _visible_glove_region(_glove(), GAME, snap, OWN_PID, IDENT)
    assert r.isEmpty()


def test_region_ignores_windows_below_the_game():
    snap = [(GAME, (0, 0, 800, 600), 777),
            (FOREIGN, (0, 0, 900, 600), 555)]   # below the game in z
    r = _visible_glove_region(_glove(), GAME, snap, OWN_PID, IDENT)
    assert r == QRegion(QRect(0, 0, CURSOR_SIZE, CURSOR_SIZE))


def test_region_ignores_own_process_windows():
    snap = [(APP_WIN, (0, 0, 900, 600), OWN_PID),  # the float cluster
            (GAME, (0, 0, 800, 600), 777)]
    r = _visible_glove_region(_glove(), GAME, snap, OWN_PID, IDENT)
    assert r == QRegion(QRect(0, 0, CURSOR_SIZE, CURSOR_SIZE))


def test_region_clips_to_game_edge():
    # Game ends at x=116: the glove pokes past its right edge.
    snap = [(GAME, (0, 0, 116, 600), 777)]
    r = _visible_glove_region(_glove(), GAME, snap, OWN_PID, IDENT)
    assert r == QRegion(QRect(0, 0, 16, CURSOR_SIZE))


def test_region_empty_when_game_absent():
    snap = [(FOREIGN, (0, 0, 900, 600), 555)]
    r = _visible_glove_region(_glove(), GAME, snap, OWN_PID, IDENT)
    assert r.isEmpty()


def test_region_fails_open_without_snapshot():
    assert _visible_glove_region(_glove(), GAME, None, OWN_PID, IDENT) is None


# ---------------------------------------------------------------------------
# Controller integration (fed via _on_pointer_event, probe injected)
# ---------------------------------------------------------------------------

@pytest.fixture
def gated(qapp):
    ctrl = GhostCursorController(
        service=None,
        settings_manager=None,
        slot_window_resolver=lambda slot: str(GAME) if slot == 0
        else str(OTHER_GAME),
    )
    assert ctrl._disabled_reason is None, ctrl._disabled_reason
    ctrl._occlusion_gated = True
    ctrl._own_pid = OWN_PID
    ctrl._to_logical = IDENT
    state = {"snap": [(GAME, (0, 0, 1600, 1200), 777)]}
    ctrl._zorder_probe = lambda: state["snap"]
    yield ctrl, state
    ctrl._hide_all()


def _press(ctrl, slot=0, x=100, y=100):
    ctrl._on_pointer_event(("press", [(slot, x, y)]))
    QApplication.processEvents()


def test_glove_shows_unmasked_over_open_game(gated):
    ctrl, state = gated
    _press(ctrl)
    ov = ctrl._overlays[0]
    assert ov.isVisible() is True
    assert ov._occ_region is None          # full region -> mask cleared


def test_glove_masked_at_occluder_edge(gated):
    ctrl, state = gated
    gx, gy = 100 - HOTSPOT[0], 100 - HOTSPOT[1]
    state["snap"] = [(FOREIGN, (gx + 16, 0, 900, 600), 555),
                     (GAME, (0, 0, 1600, 1200), 777)]
    _press(ctrl)
    ov = ctrl._overlays[0]
    assert ov.isVisible() is True
    assert ov._occ_region == QRegion(QRect(0, 0, 16, CURSOR_SIZE))


def test_glove_hidden_when_fully_covered(gated):
    ctrl, state = gated
    state["snap"] = [(FOREIGN, (0, 0, 1600, 1200), 555),
                     (GAME, (0, 0, 1600, 1200), 777)]
    _press(ctrl)
    assert 0 in ctrl._occlusion_hidden
    ov = ctrl._overlays.get(0)
    assert ov is None or ov.isVisible() is False


def test_probe_failure_fails_open(gated):
    ctrl, state = gated
    ctrl._zorder_probe = lambda: None
    _press(ctrl)
    ov = ctrl._overlays[0]
    assert ov.isVisible() is True
    assert ov._occ_region is None


def test_sweep_carves_when_occluder_arrives(gated):
    ctrl, state = gated
    _press(ctrl)
    ov = ctrl._overlays[0]
    assert ov._occ_region is None
    gx = 100 - HOTSPOT[0]
    state["snap"] = [(FOREIGN, (gx + 16, 0, 900, 600), 555),
                     (GAME, (0, 0, 1600, 1200), 777)]
    ctrl._occlusion_sweep()
    assert ov.isVisible() is True
    assert ov._occ_region == QRegion(QRect(0, 0, 16, CURSOR_SIZE))


def test_sweep_hides_then_reshows_across_full_cover(gated):
    ctrl, state = gated
    _press(ctrl)
    ov = ctrl._overlays[0]
    state["snap"] = [(FOREIGN, (0, 0, 1600, 1200), 555),
                     (GAME, (0, 0, 1600, 1200), 777)]
    ctrl._occlusion_sweep()
    assert ov.isVisible() is False
    assert 0 in ctrl._occlusion_hidden
    state["snap"] = [(GAME, (0, 0, 1600, 1200), 777)]
    ctrl._occlusion_sweep()
    assert ov.isVisible() is True
    assert 0 not in ctrl._occlusion_hidden


def test_sweep_respects_focus_suppression(gated):
    ctrl, state = gated
    state["snap"] = [(FOREIGN, (0, 0, 1600, 1200), 555),
                     (GAME, (0, 0, 1600, 1200), 777)]
    _press(ctrl)
    ctrl.set_focused_window(str(GAME))
    state["snap"] = [(GAME, (0, 0, 1600, 1200), 777)]
    ctrl._occlusion_sweep()
    ov = ctrl._overlays.get(0)
    assert ov is None or ov.isVisible() is False


def test_hide_all_clears_gate_state(gated):
    ctrl, state = gated
    _press(ctrl)
    ctrl._hide_all()
    assert ctrl._occlusion_hidden == set()
    assert ctrl._last_logical == {}
    timer = ctrl._occlusion_timer
    assert timer is None or timer.isActive() is False


def test_gate_off_keeps_legacy_behavior(qapp):
    ctrl = GhostCursorController(service=None, settings_manager=None)
    assert ctrl._occlusion_gated is False   # not win32 here
    ctrl._zorder_probe = lambda: [(FOREIGN, (0, 0, 1600, 1200), 555)]
    _press(ctrl)
    assert ctrl._overlays[0].isVisible() is True
    ctrl._hide_all()
