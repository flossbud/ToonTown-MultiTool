"""XlibBackend pointer-event construction tests with a fake Display."""
from Xlib import X

from utils.xlib_backend import XlibBackend


class _FakeWin:
    def __init__(self):
        self.sent = []  # (event, propagate, event_mask)

    def send_event(self, ev, propagate=False, event_mask=0):
        self.sent.append((ev, propagate, event_mask))


class _FakeScreen:
    root = "ROOT"


class _FakeDisplay:
    def __init__(self, win):
        self._win = win
        self.flushed = 0

    def create_resource_object(self, kind, wid):
        assert kind == "window"
        return self._win

    def screen(self):
        return _FakeScreen()

    def flush(self):
        self.flushed += 1


def _backend_with_fake():
    b = XlibBackend()
    w = _FakeWin()
    b._display = _FakeDisplay(w)
    return b, w


def test_button_press_event_fields():
    b, w = _backend_with_fake()
    ok = b.send_button_press("123", x=40, y=50, root_x=140, root_y=250,
                             state=0, time=999)
    assert ok and len(w.sent) == 1
    ev, propagate, mask = w.sent[0]
    assert ev.type == X.ButtonPress
    assert ev.detail == 1
    assert (ev.event_x, ev.event_y) == (40, 50)
    assert (ev.root_x, ev.root_y) == (140, 250)
    assert ev.time == 999
    assert ev.same_screen == 1
    assert propagate is False


def test_button_release_carries_state():
    b, w = _backend_with_fake()
    b.send_button_release("123", x=1, y=2, root_x=3, root_y=4,
                          state=X.Button1Mask, time=1000)
    ev, _, _ = w.sent[0]
    assert ev.type == X.ButtonRelease
    assert ev.state & X.Button1Mask


def test_motion_event():
    b, w = _backend_with_fake()
    b.send_motion("123", x=10, y=20, root_x=30, root_y=40,
                  state=X.Button1Mask, time=5)
    ev, _, _ = w.sent[0]
    assert ev.type == X.MotionNotify
    assert ev.detail == 0


def test_no_display_returns_false():
    b = XlibBackend()
    assert b.send_button_press("1", 0, 0, 0, 0) is False


def test_zero_mask_variant():
    # The spike decides the delivery mode; both variants must work.
    b, w = _backend_with_fake()
    b._POINTER_MASKED = False
    b.send_button_press("123", x=1, y=2, root_x=3, root_y=4)
    _, _, mask = w.sent[0]
    assert mask == 0


def test_masked_variant_uses_button_press_mask():
    b, w = _backend_with_fake()
    b._POINTER_MASKED = True
    b.send_button_press("123", x=1, y=2, root_x=3, root_y=4)
    _, _, mask = w.sent[0]
    assert mask == X.ButtonPressMask
