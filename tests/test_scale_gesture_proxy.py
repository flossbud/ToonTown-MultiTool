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


def test_set_scale_updates_live_scale(qapp):
    pw = _make(base_scale=1.0)
    assert pw._scale == 1.0
    pw.set_scale(1.4)
    assert pw._scale == 1.4


def test_wheel_event_emits_notch_count(qapp):
    pw = _make()
    got = []
    pw.wheel_notch.connect(got.append)

    ev = QWheelEvent(
        QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, 120),
        Qt.NoButton, Qt.NoModifier, Qt.ScrollUpdate, False,
    )
    pw.wheelEvent(ev)
    assert got == [1]


def test_wheel_event_negative_multi_notch(qapp):
    pw = _make()
    got = []
    pw.wheel_notch.connect(got.append)

    ev = QWheelEvent(
        QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, -240),
        Qt.NoButton, Qt.NoModifier, Qt.ScrollUpdate, False,
    )
    pw.wheelEvent(ev)
    assert got == [-2]


def test_window_flags_and_attributes(qapp):
    pw = _make()
    flags = pw.windowFlags()
    assert flags & Qt.FramelessWindowHint
    assert flags & Qt.WindowStaysOnTopHint
    assert flags & Qt.X11BypassWindowManagerHint
    assert pw.testAttribute(Qt.WA_TranslucentBackground)
