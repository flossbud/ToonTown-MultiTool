"""Confined ghost cursors (xcb transient-to-game mode) offscreen tests.

The WM-side behavior (transient rides directly above the game window, under
occluders) was live-probed on KWin Wayland 2026-07-02 and cannot run
offscreen; these tests cover the renderer logic around it: mode gating,
flag selection, the per-map confine latch with opacity staging, keep-mapped
hides, target rewrites, and edge clipping.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

from PySide6.QtCore import QObject, QRect, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

from tabs.multitoon import _ghost_cursors as gc


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class FakeService(QObject):
    ghost_pointer_event = Signal(object)
    ghost_clear = Signal()


@pytest.fixture
def confine_calls(monkeypatch):
    """Route x11_transient.confine into a recorder (returns True)."""
    calls = []
    monkeypatch.setattr(gc.x11_transient, "confine",
                        lambda ghost, game: calls.append((ghost, game)) or True)
    return calls


def make_overlay(qapp, confined=True):
    pm = QPixmap(gc.CURSOR_SIZE, gc.CURSOR_SIZE)
    pm.fill(Qt.transparent)
    return gc.GhostCursorOverlay(pm, confined=confined)


# -- mode gating -------------------------------------------------------------

def test_confinement_reason_kill_switch(monkeypatch):
    monkeypatch.setenv("TTMT_GHOST_UNCONFINED", "1")
    assert "TTMT_GHOST_UNCONFINED" in gc._confinement_reason()


def test_confinement_reason_rejects_non_xcb(qapp):
    # offscreen has no WM: confined mode must not engage
    reason = gc._confinement_reason()
    assert reason is not None and "offscreen" in reason


def test_controller_defaults_to_legacy_flags_offscreen(qapp):
    ctl = gc.GhostCursorController(None, None)
    assert ctl._confined is False
    ov = ctl._overlay_for(0)
    assert ov.windowFlags() & Qt.WindowStaysOnTopHint
    ov.deleteLater()


def test_controller_stamp_names_the_mode(qapp, capsys):
    gc.GhostCursorController(None, None)
    out = capsys.readouterr().out
    assert "[GhostCursors] mode: unconfined float" in out


# -- overlay flags -----------------------------------------------------------

def test_confined_overlay_is_managed_not_on_top(qapp):
    ov = make_overlay(qapp)
    flags = ov.windowFlags()
    assert not flags & Qt.WindowStaysOnTopHint
    assert not flags & Qt.X11BypassWindowManagerHint
    # plain Window type: Qt.Tool couples surfaces to main-window minimize
    # (project_transparent_mode_qt_tool_minimize_coupling)
    assert flags & Qt.WindowType_Mask == Qt.Window
    assert flags & Qt.FramelessWindowHint
    assert flags & Qt.WindowTransparentForInput
    assert flags & Qt.WindowDoesNotAcceptFocus
    ov.deleteLater()


# -- per-map confine latch + opacity staging ---------------------------------

def test_show_stages_opacity_until_confined(qapp, confine_calls):
    ov = make_overlay(qapp)
    ov.set_game_window(777)
    ov.show_at(100, 100)
    assert ov.isVisible()
    assert ov.windowOpacity() == 0.0        # staged: pre-transient gap
    ov._confine()
    assert ov.windowOpacity() == 1.0
    assert confine_calls == [(int(ov.winId()), 777)]
    ov._confine()                            # idempotent per map
    assert len(confine_calls) == 1
    ov.hide_now()
    ov.deleteLater()


def test_remap_reasserts_confinement(qapp, confine_calls):
    ov = make_overlay(qapp)
    ov.set_game_window(777)
    ov.show_at(100, 100)
    ov._confine()
    ov.hide()                                # real unmap (e.g. Qt teardown)
    ov.show_at(120, 120)                     # remap -> latch reset
    assert ov.windowOpacity() == 0.0
    ov._confine()
    assert len(confine_calls) == 2
    ov.deleteLater()


def test_game_window_change_rewrites_target(qapp, confine_calls):
    ov = make_overlay(qapp)
    ov.set_game_window(777)
    ov.show_at(100, 100)
    ov._confine()
    ov.set_game_window(888)                  # window list reshuffled
    assert confine_calls[-1] == (int(ov.winId()), 888)
    ov.set_game_window(888)                  # unchanged: no property traffic
    assert len(confine_calls) == 2
    ov.deleteLater()


def test_confine_failure_warns_and_survives(qapp, monkeypatch, capsys):
    monkeypatch.setattr(gc.x11_transient, "confine", lambda *_a: False)
    ov = make_overlay(qapp)
    ov.set_game_window(777)
    ov.show_at(100, 100)
    ov._confine()
    assert "confinement failed" in capsys.readouterr().out
    assert ov.windowOpacity() == 1.0         # ghost still usable, unconfined
    ov.deleteLater()


# -- keep-mapped hides -------------------------------------------------------

def test_hide_now_keeps_confined_overlay_mapped(qapp, confine_calls):
    ov = make_overlay(qapp)
    ov.set_game_window(777)
    ov.show_at(100, 100)
    ov._confine()
    ov.hide_now()
    assert ov.isVisible()                    # mapped, just invisible
    assert ov.windowOpacity() == 0.0
    ov.show_at(150, 150)                     # instant re-show, no remap
    assert ov.windowOpacity() == 1.0
    assert len(confine_calls) == 1
    ov.deleteLater()


def test_legacy_hide_now_still_unmaps(qapp):
    ov = make_overlay(qapp, confined=False)
    ov.show_at(100, 100)
    ov.hide_now()
    assert not ov.isVisible()
    ov.deleteLater()


def test_fade_finish_does_not_unmap_confined(qapp, confine_calls):
    ov = make_overlay(qapp)
    ov.set_game_window(777)
    ov.show_at(100, 100)
    ov._confine()
    ov.fade_out()
    ov._fade.finished.emit()                 # legacy connects this to hide()
    assert ov.isVisible()
    ov.deleteLater()


def test_suppression_before_confine_stays_invisible(qapp, confine_calls):
    ov = make_overlay(qapp)
    ov.set_game_window(777)
    ov.show_at(100, 100)                     # staged at 0
    ov.hide_now()                            # focus suppression in the gap
    ov._confine()                            # paint lands afterwards
    assert ov.windowOpacity() == 0.0         # must NOT pop back to 1
    ov.deleteLater()


# -- edge clipping -----------------------------------------------------------

def test_clip_inside_game_rect_is_unmasked(qapp, confine_calls):
    ov = make_overlay(qapp)
    ov.show_at(200, 200)
    ov.clip_to((0, 0, 1000, 1000))
    assert ov.mask().isEmpty()               # no mask installed
    ov.deleteLater()


def test_clip_at_game_edge_masks_overhang(qapp, confine_calls):
    ov = make_overlay(qapp)
    ov.show_at(101, 103)                     # hotspot -> pos (100, 100)
    ov.clip_to((0, 0, 116, 116))             # game ends 16px into the glove
    assert ov.mask().boundingRect() == QRect(0, 0, 16, 16)
    ov.clip_to(None)
    assert ov.mask().isEmpty()
    ov.deleteLater()


def test_clip_is_noop_on_legacy_overlay(qapp):
    ov = make_overlay(qapp, confined=False)
    ov.show_at(101, 103)
    ov.clip_to((0, 0, 10, 10))
    assert ov.mask().isEmpty()
    ov.deleteLater()


# -- controller pipeline (confined forced on) --------------------------------

@pytest.fixture
def confined_rig(qapp, monkeypatch, confine_calls):
    monkeypatch.setattr(gc, "_confinement_reason", lambda: None)
    svc = FakeService()
    ctl = gc.GhostCursorController(
        svc, None,
        slot_window_resolver=lambda slot: "777" if slot == 1 else None,
        slot_rect_resolver=lambda slot: (0, 0, 116, 116) if slot == 1 else None)
    yield svc, ctl, confine_calls
    ctl._hide_all()
    for ov in ctl._overlays.values():
        ov.deleteLater()


def test_pointer_event_targets_and_clips(confined_rig):
    svc, ctl, calls = confined_rig
    assert ctl._confined is True
    svc.ghost_pointer_event.emit(("motion", [(1, 101, 103)]))
    ov = ctl._overlays[1]
    assert ov._game_wid == 777
    assert ov.isVisible()
    assert ov.mask().boundingRect() == QRect(0, 0, 16, 16)
    ov._confine()
    assert calls == [(int(ov.winId()), 777)]


def test_pointer_event_without_rect_leaves_unclipped(confined_rig):
    svc, ctl, _calls = confined_rig
    ctl._slot_rect_resolver = lambda slot: None
    svc.ghost_pointer_event.emit(("motion", [(1, 101, 103)]))
    assert ctl._overlays[1].mask().isEmpty()
