"""Attach strategies: which one runs where, and the occlusion maths."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QRegion

from utils import x11_transient
from utils.strips import attach
from utils.strips.attach import (AttachStrategy, CocoaPanelAttach,
                                 Win32TopmostAttach, X11TransientAttach,
                                 pick_attach_strategy)


@pytest.fixture(autouse=True)
def _no_override(monkeypatch):
    monkeypatch.delenv("TTMT_STRIPS_ATTACH", raising=False)


def test_x11_gets_the_transient_strategy(monkeypatch):
    monkeypatch.setattr(x11_transient, "available", lambda: True)
    assert pick_attach_strategy("xcb").name == "x11-transient"


def test_x11_without_xlib_falls_back_to_floating(monkeypatch):
    monkeypatch.setattr(x11_transient, "available", lambda: False)
    assert pick_attach_strategy("xcb").name == "floating"


def test_windows_and_macos(monkeypatch):
    monkeypatch.setattr(attach.sys, "platform", "win32")
    assert pick_attach_strategy("windows").name == "win32-topmost-gate"
    monkeypatch.setattr(attach.sys, "platform", "darwin")
    assert pick_attach_strategy("cocoa").name == "cocoa-panel-gate"


def test_anything_else_floats(qapp):
    assert pick_attach_strategy("offscreen").name == "floating"
    assert pick_attach_strategy("wayland").name == "floating"
    assert pick_attach_strategy().name == "floating"      # the test platform


def test_environment_can_force_a_strategy(monkeypatch):
    monkeypatch.setenv("TTMT_STRIPS_ATTACH", "floating")
    monkeypatch.setattr(x11_transient, "available", lambda: True)
    assert pick_attach_strategy("xcb").name == "floating"
    monkeypatch.setenv("TTMT_STRIPS_ATTACH", "no-such-thing")
    assert pick_attach_strategy("xcb").name == "x11-transient"


def test_only_the_x11_strip_is_not_keep_above():
    """On X11 the strip's place in the stack comes from the game window; a
    keep-above strip would float over windows covering the game."""
    assert not (X11TransientAttach().window_flags() & Qt.WindowStaysOnTopHint)
    for cls in (AttachStrategy, Win32TopmostAttach, CocoaPanelAttach):
        assert cls().window_flags() & Qt.WindowStaysOnTopHint


def test_no_strip_window_accepts_focus_or_has_a_frame():
    for cls in (AttachStrategy, X11TransientAttach, Win32TopmostAttach,
                CocoaPanelAttach):
        flags = cls().window_flags()
        assert flags & Qt.WindowDoesNotAcceptFocus
        assert flags & Qt.FramelessWindowHint
    # The macOS panel must be a Tool window (NSPanel).
    assert (CocoaPanelAttach().window_flags() & Qt.WindowType_Mask) == Qt.Tool


def test_gated_flags():
    assert not X11TransientAttach().gated and not AttachStrategy().gated
    assert Win32TopmostAttach().gated and CocoaPanelAttach().gated
    assert CocoaPanelAttach().logical_native
    assert not Win32TopmostAttach().logical_native


class _Surface:
    def __init__(self, wid=0x1400007):
        self._wid = wid

    def winId(self):
        return self._wid


def test_x11_attach_confines_to_the_game_window(monkeypatch):
    calls = []
    monkeypatch.setattr(x11_transient, "confine",
                        lambda strip, game: calls.append((strip, game)) or True)
    s = X11TransientAttach()
    assert s.attach(_Surface(), None, "18874375") is True
    assert calls == [(0x1400007, 18874375)]
    assert s.attach(_Surface(), None, "not-a-window") is False


def test_x11_prepare_sets_skip_lists_before_the_map(monkeypatch):
    calls = []
    monkeypatch.setattr(x11_transient, "premap_skip_lists",
                        lambda wid: calls.append(wid) or True)
    X11TransientAttach().prepare(_Surface(77), None)
    assert calls == [77]


class _Backend:
    def __init__(self):
        self.calls = []

    def set_initial_state(self, w):
        self.calls.append("initial")

    def set_above(self, w):
        self.calls.append("above")

    def set_non_activating(self, w):
        self.calls.append("non_activating")

    def _nswindow(self, w):
        return None


def test_win32_and_cocoa_use_the_overlay_backend():
    for cls in (Win32TopmostAttach, CocoaPanelAttach):
        b = _Backend()
        s = cls()
        s.prepare(_Surface(), b)
        assert s.attach(_Surface(), b, "42") is True
        assert b.calls == ["initial", "above", "non_activating"]


# -- occlusion maths (shared by the Windows and macOS gates) -------------------

STRIP = QRect(300, 110, 400, 60)          # logical, global
GAME = (100, 100, 900, 700)               # left, top, right, bottom


def _same(x, y):
    return x, y


def gate(snapshot, own=()):
    return attach._gate_region(STRIP, "10", snapshot, own, _same)


def test_no_snapshot_means_show_everything():
    assert gate(None) is None


def test_game_not_on_screen_means_show_nothing():
    assert gate([(99, (0, 0, 50, 50), 1)]).isEmpty()


def test_uncovered_strip_is_whole():
    region = gate([(10, GAME, 500)])
    assert region == QRegion(QRect(0, 0, 400, 60))


def test_a_window_above_the_game_carves_the_strip():
    # Top-first: window 20 is above the game and covers the strip's left half.
    region = gate([(20, (0, 0, 500, 400), 700), (10, GAME, 500)])
    assert region == QRegion(QRect(200, 0, 200, 60))


def test_a_window_below_the_game_does_not_occlude():
    region = gate([(10, GAME, 500), (20, (0, 0, 500, 400), 700)])
    assert region == QRegion(QRect(0, 0, 400, 60))


def test_fully_covered_is_empty():
    assert gate([(20, (0, 0, 2000, 2000), 700), (10, GAME, 500)]).isEmpty()


def test_own_strip_surfaces_never_occlude_but_the_apps_other_windows_do():
    snapshot = [(31, (250, 100, 760, 180), 500),    # this strip's own surface
                (10, GAME, 900)]
    assert gate(snapshot, own=[31]) == QRegion(QRect(0, 0, 400, 60))
    # Same pid as the strips (500), but not a strip: the main window covers.
    snapshot = [(40, (0, 0, 500, 400), 500), (31, (250, 100, 760, 180), 500),
                (10, GAME, 900)]
    assert gate(snapshot, own=[31]) == QRegion(QRect(200, 0, 200, 60))


def test_strip_is_clipped_to_its_game_window():
    region = attach._gate_region(QRect(50, 110, 400, 60), "10",
                                 [(10, GAME, 500)], (), _same)
    assert region == QRegion(QRect(50, 0, 350, 60))


def test_bad_window_id_fails_open():
    assert attach._gate_region(STRIP, "abc", [(10, GAME, 500)], (), _same) is None
