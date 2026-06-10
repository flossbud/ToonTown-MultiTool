"""XRecordCapture dispatch/lifecycle tests (no real X)."""
from types import SimpleNamespace

from Xlib import X

from utils.xrecord_capture import XRecordCapture


def _ev(type_, detail=1, send_event=0):
    return SimpleNamespace(type=type_, detail=detail, send_event=send_event,
                           root_x=10, root_y=20, state=0, time=111)


def test_dispatch_button1_press_release_and_motion():
    got = []
    cap = XRecordCapture(lambda *a: got.append(a))
    cap._dispatch(_ev(X.ButtonPress))
    cap._dispatch(_ev(X.ButtonRelease))
    cap._dispatch(_ev(X.MotionNotify, detail=0))
    kinds = [g[0] for g in got]
    assert kinds == ["press", "release", "motion"]
    assert got[0][1:] == (10, 20, 0, 111)  # root_x, root_y, state, time


def test_dispatch_ignores_other_buttons_and_synthetic():
    got = []
    cap = XRecordCapture(lambda *a: got.append(a))
    cap._dispatch(_ev(X.ButtonPress, detail=3))          # right button
    cap._dispatch(_ev(X.ButtonPress, send_event=1))      # defensive: synthetic
    assert got == []


def test_not_running_initially_and_stop_idempotent():
    cap = XRecordCapture(lambda *a: None)
    assert cap.is_running() is False
    cap.stop()
    cap.stop()  # second stop must not raise


def test_on_died_callback_optional():
    # Constructing without on_died must work (default None).
    cap = XRecordCapture(lambda *a: None)
    assert cap._on_died is None
    died = []
    cap2 = XRecordCapture(lambda *a: None, on_died=lambda: died.append(1))
    assert cap2._on_died is not None
