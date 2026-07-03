"""Win32 ghost-cursor occlusion gate (offscreen, probes injected).

On Windows the gloves are unconfined always-on-top floats; the gate hides a
glove whenever the top-level under its point is a FOREIGN window (neither the
slot's own game window nor any window of this process), and the periodic
sweep re-shows it when the occluder moves away. All OS probes are instance
attributes, faked here.
"""
import pytest
from PySide6.QtWidgets import QApplication

from tabs.multitoon._ghost_cursors import GhostCursorController

GAME_WID = 111
OTHER_GAME_WID = 222
FOREIGN_HWND = 333
APP_HWND = 444
OWN_PID = 4242


@pytest.fixture
def gated(qapp):
    """Controller with the gate forced on and fake probes installed."""
    ctrl = GhostCursorController(
        service=None,
        settings_manager=None,
        slot_window_resolver=lambda slot: str(GAME_WID) if slot == 0
        else str(OTHER_GAME_WID),
    )
    assert ctrl._disabled_reason is None, ctrl._disabled_reason
    ctrl._occlusion_gated = True
    ctrl._own_pid = OWN_PID
    state = {"top": GAME_WID, "pids": {FOREIGN_HWND: 555, APP_HWND: OWN_PID}}
    ctrl._top_probe = lambda x, y: state["top"]
    ctrl._pid_probe = lambda hwnd: state["pids"].get(hwnd)
    yield ctrl, state
    ctrl._hide_all()


def _press(ctrl, slot=0, x=100, y=100):
    ctrl._on_pointer_event(("press", [(slot, x, y)]))
    QApplication.processEvents()


def test_glove_shows_over_own_game_window(gated):
    ctrl, state = gated
    state["top"] = GAME_WID
    _press(ctrl)
    assert ctrl._overlays[0].isVisible() is True
    assert 0 not in ctrl._occlusion_hidden


def test_glove_hidden_over_foreign_window(gated):
    ctrl, state = gated
    state["top"] = FOREIGN_HWND
    _press(ctrl)
    assert 0 in ctrl._occlusion_hidden
    ov = ctrl._overlays.get(0)
    assert ov is None or ov.isVisible() is False


def test_glove_shows_over_own_process_window(gated):
    ctrl, state = gated
    state["top"] = APP_HWND            # e.g. the float cluster / main window
    _press(ctrl)
    assert ctrl._overlays[0].isVisible() is True


def test_probe_failure_fails_open(gated):
    ctrl, state = gated
    state["top"] = None
    _press(ctrl)
    assert ctrl._overlays[0].isVisible() is True


def test_sweep_hides_when_occluder_arrives(gated):
    ctrl, state = gated
    state["top"] = GAME_WID
    _press(ctrl)
    assert ctrl._overlays[0].isVisible() is True
    state["top"] = FOREIGN_HWND        # a window moved over the glove
    ctrl._occlusion_sweep()
    assert ctrl._overlays[0].isVisible() is False
    assert 0 in ctrl._occlusion_hidden


def test_sweep_reshows_when_occluder_leaves(gated):
    ctrl, state = gated
    state["top"] = FOREIGN_HWND
    _press(ctrl)
    assert 0 in ctrl._occlusion_hidden
    state["top"] = GAME_WID            # the occluder moved away
    ctrl._occlusion_sweep()
    assert ctrl._overlays[0].isVisible() is True
    assert 0 not in ctrl._occlusion_hidden


def test_sweep_respects_focus_suppression(gated):
    ctrl, state = gated
    state["top"] = FOREIGN_HWND
    _press(ctrl)
    ctrl.set_focused_window(str(GAME_WID))   # slot 0's window took focus
    state["top"] = GAME_WID
    ctrl._occlusion_sweep()
    ov = ctrl._overlays.get(0)
    assert ov is None or ov.isVisible() is False


def test_hide_all_clears_gate_state(gated):
    ctrl, state = gated
    state["top"] = FOREIGN_HWND
    _press(ctrl)
    ctrl._hide_all()
    assert ctrl._occlusion_hidden == set()
    assert ctrl._last_raw == {}
    timer = ctrl._occlusion_timer
    assert timer is None or timer.isActive() is False


def test_gate_off_keeps_legacy_behavior(qapp):
    ctrl = GhostCursorController(service=None, settings_manager=None)
    assert ctrl._occlusion_gated is False   # not win32 here
    ctrl._top_probe = lambda x, y: FOREIGN_HWND
    ctrl._pid_probe = lambda hwnd: 555
    _press(ctrl)
    assert ctrl._overlays[0].isVisible() is True
    ctrl._hide_all()
