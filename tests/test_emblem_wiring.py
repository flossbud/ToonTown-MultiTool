"""Tests for wiring the _Emblem gesture signals to the OverlayGroupController
(Task 5.1): connect_emblem maps toggle/move/scroll to toggle()/begin_group_drag()/
set_scale_by_notches(), and begin_group_drag() follows the global cursor (a poll)
moving the group anchor until the left button releases.

Run (NEVER the whole tests/ dir):
    TTMT_NO_VENV_REEXEC=1 QT_QPA_PLATFORM=offscreen ./venv/bin/python -m pytest \
        tests/test_emblem_wiring.py -q
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

from PySide6.QtCore import QObject, Signal, QPoint, Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication

from utils.overlay.backend import NoOpOverlayBackend
from utils.overlay.group_controller import OverlayGroupController


class _StubWindow:
    def showMinimized(self):
        pass

    def showNormal(self):
        pass


class _SignalEmblem(QObject):
    """Minimal stand-in carrying the three real _Emblem gesture signals."""
    toggle_requested = Signal()
    move_requested = Signal()
    resize_scrolled = Signal(int)


def _ctl():
    return OverlayGroupController(_StubWindow(), backend=NoOpOverlayBackend())


def test_connect_emblem_wires_the_three_signals(qapp):
    ctl = _ctl()
    calls = {"toggle": 0, "drag": 0, "scale": []}
    # Record what the signals invoke (set BEFORE connect so the bound lookups
    # resolve to these instance attributes).
    ctl.toggle = lambda: calls.__setitem__("toggle", calls["toggle"] + 1)
    ctl.begin_group_drag = lambda: calls.__setitem__("drag", calls["drag"] + 1)
    ctl.set_scale_by_notches = lambda n: calls["scale"].append(n)

    emblem = _SignalEmblem()
    ctl.connect_emblem(emblem)
    assert ctl._emblem is emblem

    emblem.toggle_requested.emit()
    emblem.move_requested.emit()
    emblem.resize_scrolled.emit(2)

    assert calls["toggle"] == 1
    assert calls["drag"] == 1
    assert calls["scale"] == [2]  # the int notch passed through


def test_connect_emblem_is_idempotent_no_double_fire(qapp):
    ctl = _ctl()
    calls = {"toggle": 0}
    ctl.toggle = lambda: calls.__setitem__("toggle", calls["toggle"] + 1)
    emblem = _SignalEmblem()
    ctl.connect_emblem(emblem)
    ctl.connect_emblem(emblem)  # re-connect the SAME emblem must NOT double-fire
    emblem.toggle_requested.emit()
    assert calls["toggle"] == 1


def test_connect_emblem_rebinds_to_a_new_emblem(qapp):
    ctl = _ctl()
    calls = {"toggle": 0}
    ctl.toggle = lambda: calls.__setitem__("toggle", calls["toggle"] + 1)
    old, new = _SignalEmblem(), _SignalEmblem()
    ctl.connect_emblem(old)
    ctl.connect_emblem(new)  # drops old's connections
    old.toggle_requested.emit()   # the old emblem no longer drives the controller
    assert calls["toggle"] == 0
    new.toggle_requested.emit()
    assert calls["toggle"] == 1
    assert ctl._emblem is new


def test_begin_group_drag_noop_when_framed(qapp):
    ctl = _ctl()  # _active is False
    ctl.begin_group_drag()
    assert ctl._drag_timer is None, "no drag should start while framed"


def test_begin_group_drag_follows_cursor_and_ends_on_release(qapp, monkeypatch):
    ctl = _ctl()
    ctl._active = True
    moves = []
    ctl.move_group = lambda dx, dy: moves.append((dx, dy))

    # Cursor advances; the button stays down for two steps then releases.
    positions = iter([QPoint(100, 100), QPoint(110, 115), QPoint(112, 113)])
    buttons = iter([Qt.LeftButton, Qt.LeftButton, Qt.NoButton])
    monkeypatch.setattr(QCursor, "pos", lambda: next(positions))
    monkeypatch.setattr(QApplication, "mouseButtons", lambda: next(buttons))

    ctl.begin_group_drag()  # consumes positions[0] as the drag origin
    assert ctl._drag_timer is not None and ctl._drag_timer.isActive()

    ctl._drag_step()  # Left + (110,115): delta (10,15)
    ctl._drag_step()  # Left + (112,113): delta (2,-2)
    ctl._drag_step()  # NoButton -> end the drag

    assert moves == [(10, 15), (2, -2)]
    assert not ctl._drag_timer.isActive(), "drag must stop on release"
    assert ctl._drag_last is None


def test_begin_group_drag_ends_if_left_transparent_mode(qapp, monkeypatch):
    ctl = _ctl()
    ctl._active = True
    monkeypatch.setattr(QCursor, "pos", lambda: QPoint(0, 0))
    monkeypatch.setattr(QApplication, "mouseButtons", lambda: Qt.LeftButton)
    ctl.begin_group_drag()
    assert ctl._drag_timer.isActive()
    ctl._active = False  # e.g. leave() raced in
    ctl._drag_step()
    assert not ctl._drag_timer.isActive()
