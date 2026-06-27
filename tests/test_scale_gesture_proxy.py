"""Unit tests for ScaleProxyWindow.

The proxy's rendering and override-redirect stacking are LIVE-only (the
offscreen Qt platform cannot composite translucent surfaces or honor
override-redirect z-order), so these tests assert only the pure, observable
contract: snapshot/scale storage, ``set_scale`` updating the live scale, the
wheel-notch forwarding, and the window flags/attributes.
"""

from PySide6.QtCore import Qt, QRect, QPoint, QPointF
from PySide6.QtGui import QImage, QWheelEvent

from utils.overlay.scale_gesture_proxy import ScaleProxyWindow


def _img(w, h):
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    img.fill(0xFF112233)
    return img


def _make(base_scale=1.0):
    snapshot = _img(40, 30)
    bbox = QRect(100, 50, 40, 30)
    anchor = QPoint(120, 65)
    return ScaleProxyWindow(snapshot, bbox, anchor, base_scale)


def _wheel(dy):
    return QWheelEvent(
        QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, dy),
        Qt.NoButton, Qt.NoModifier, Qt.ScrollUpdate, False,
    )


def test_stores_snapshot_and_base_scale(qapp):
    snap = _img(40, 30)
    pw = ScaleProxyWindow(snap, QRect(100, 50, 40, 30), QPoint(120, 65), 0.8)
    assert pw._snapshot is snap
    assert pw._base_scale == 0.8
    assert pw._scale == 0.8


def test_set_scale_updates_live_scale_and_requests_repaint(qapp, monkeypatch):
    pw = _make(base_scale=1.0)
    assert pw._scale == 1.0
    updated = []
    monkeypatch.setattr(pw, "update", lambda *a, **k: updated.append(1))
    pw.set_scale(1.4)
    assert pw._scale == 1.4
    assert updated == [1]            # set_scale must request a repaint


def test_wheel_event_emits_one_notch_per_event(qapp):
    # Sign-based, matching the emblem (_compact_layout _Emblem.wheelEvent): one
    # notch per wheel event regardless of magnitude, so trackpad/high-res deltas
    # are not floor-divided away and the sign is consistent both directions.
    pw = _make()
    got = []
    pw.wheel_notch.connect(got.append)
    pw.wheelEvent(_wheel(120))
    pw.wheelEvent(_wheel(-240))      # magnitude ignored -> still one notch
    pw.wheelEvent(_wheel(40))        # small (trackpad) positive -> +1, not 0
    pw.wheelEvent(_wheel(0))         # no movement -> no emit
    assert got == [1, -1, 1]


def test_non_wheel_pointer_events_are_swallowed(qapp):
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtCore import QEvent
    pw = _make()
    ev = QMouseEvent(QEvent.MouseButtonPress, QPointF(5, 5), Qt.LeftButton,
                     Qt.LeftButton, Qt.NoModifier)
    pw.mousePressEvent(ev)
    assert ev.isAccepted()           # consumed, not passed through


def test_window_flags_and_attributes(qapp):
    pw = _make()
    flags = pw.windowFlags()
    assert flags & Qt.FramelessWindowHint
    assert flags & Qt.WindowStaysOnTopHint
    assert flags & Qt.WindowDoesNotAcceptFocus
    assert flags & Qt.X11BypassWindowManagerHint
    assert pw.testAttribute(Qt.WA_TranslucentBackground)
    assert pw.testAttribute(Qt.WA_ShowWithoutActivating)
    assert pw.testAttribute(Qt.WA_DeleteOnClose) is False
