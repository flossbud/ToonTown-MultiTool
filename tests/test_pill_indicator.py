"""Tests for PillIndicator — the paint-based chip pill widget."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QRectF, QAbstractAnimation
from PySide6.QtWidgets import QApplication, QWidget

import utils.motion as motion
from utils.widgets.pill_indicator import PillIndicator


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


@pytest.fixture(autouse=True)
def reset_motion(monkeypatch):
    monkeypatch.setattr(motion, "_os_reduced_motion", lambda: False)
    monkeypatch.setattr(motion, "_TEST_DURATION_SCALE", 0.0)
    monkeypatch.setattr(motion, "_settings", None)


def test_pill_starts_empty(qapp):
    parent = QWidget()
    parent.resize(400, 64)
    pill = PillIndicator(parent)
    assert pill._pill_rect.isEmpty()


def test_set_pill_rect_triggers_update(qapp):
    parent = QWidget()
    pill = PillIndicator(parent)
    r = QRectF(10, 6, 60, 52)
    pill.set_pill_rect(r)
    assert pill._pill_rect == r


def test_slide_to_animates_geometry(qapp):
    parent = QWidget()
    parent.resize(400, 64)
    pill = PillIndicator(parent)
    pill.set_pill_rect(QRectF(10, 6, 60, 52))

    target = QRectF(140, 6, 80, 52)
    anim = pill.slide_to(target)

    assert anim is not None
    # With _TEST_DURATION_SCALE=0, drive event loop to completion.
    finished = {"v": False}
    anim.finished.connect(lambda: finished.update(v=True))
    for _ in range(50):
        qapp.processEvents()
        if finished["v"]:
            break
    assert finished["v"] is True
    assert pill._pill_rect == target


def test_slide_to_when_reduced_motion_snaps(qapp, monkeypatch):
    monkeypatch.setattr(motion, "_os_reduced_motion", lambda: True)
    parent = QWidget()
    pill = PillIndicator(parent)
    pill.set_pill_rect(QRectF(10, 6, 60, 52))

    result = pill.slide_to(QRectF(140, 6, 80, 52))

    assert result is None
    assert pill._pill_rect == QRectF(140, 6, 80, 52)


def test_slide_to_interrupts_in_flight(qapp):
    parent = QWidget()
    pill = PillIndicator(parent)
    pill.set_pill_rect(QRectF(10, 6, 60, 52))
    a1 = pill.slide_to(QRectF(140, 6, 60, 52))
    a2 = pill.slide_to(QRectF(280, 6, 60, 52))
    assert a1.state() == QAbstractAnimation.Stopped
    # a2 may have completed instantly due to scale 0; just verify final state.
    for _ in range(50):
        qapp.processEvents()
        if a2.state() == QAbstractAnimation.Stopped:
            break
    assert pill._pill_rect == QRectF(280, 6, 60, 52)


def test_cancel_animation_stops_running_slide(qapp):
    """PillIndicator.cancel_animation() must stop any in-flight slide_to
    animation and leave _pill_rect at its current interpolated value.
    Callers (e.g., the rail resize filter) use this to clear the way for
    a snap-to-target without reaching into _anim directly."""
    parent = QWidget()
    parent.resize(400, 64)
    pill = PillIndicator(parent)
    pill.set_pill_rect(QRectF(10, 6, 60, 52))

    anim = pill.slide_to(QRectF(280, 6, 60, 52))
    assert anim is not None

    pill.cancel_animation()

    assert anim.state() == QAbstractAnimation.Stopped


def test_cancel_animation_noop_when_nothing_running(qapp):
    """Calling cancel_animation with no animation in flight must not
    raise — the rail resize filter calls it unconditionally on every
    resize event."""
    parent = QWidget()
    pill = PillIndicator(parent)
    pill.cancel_animation()  # should not raise

    pill.set_pill_rect(QRectF(10, 6, 60, 52))
    pill.cancel_animation()  # still no animation; still must not raise
