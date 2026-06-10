"""XRecordCapture dispatch/lifecycle/parse tests (no real X connections).

Real 32-byte event buffers are built via the keyword path of the protocol
classes (`cls(**fields)._binary` packs without a display); the reply
callback is exercised with stub reply objects.
"""
import threading
from types import SimpleNamespace

from Xlib import X
from Xlib.ext import record
from Xlib.protocol import event as xevent

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


def _reply(category=record.FromServer, swapped=False, data=b""):
    return SimpleNamespace(category=category, client_swapped=swapped,
                           data=data)


def _binary_event(cls, **kw):
    fields = dict(detail=1, time=1000, root=0, window=0, child=0,
                  root_x=10, root_y=20, event_x=0, event_y=0,
                  state=0, same_screen=1)
    fields.update(kw)
    return cls(**fields)._binary


def _stub_data_display(cap, event_classes=None):
    if event_classes is None:
        event_classes = {4: xevent.ButtonPress, 5: xevent.ButtonRelease,
                         6: xevent.MotionNotify}
    cap._data = SimpleNamespace(
        display=SimpleNamespace(
            event_classes=event_classes,
            # Window-field parsing calls display.get_resource_class();
            # None means "leave the value as a raw int", which is fine.
            get_resource_class=lambda name: None))


def test_reply_callback_guards_drop_non_event_replies():
    got = []
    cap = XRecordCapture(lambda *a: got.append(a))
    _stub_data_display(cap)
    press = _binary_event(xevent.ButtonPress)
    cap._reply_callback(_reply(category=record.StartOfData, data=press))
    cap._reply_callback(_reply(swapped=True, data=press))
    cap._reply_callback(_reply(data=b""))
    cap._reply_callback(_reply(data=b"\x01" + bytes(31)))  # code < 2: reply
    cap._stopping = True
    cap._reply_callback(_reply(data=press))
    assert got == []


def test_reply_callback_parses_multi_event_buffer():
    got = []
    cap = XRecordCapture(lambda *a: got.append(a))
    _stub_data_display(cap)
    press = _binary_event(xevent.ButtonPress, root_x=10)
    release = _binary_event(xevent.ButtonRelease, root_x=11, state=256)
    cap._reply_callback(_reply(data=press + release))
    assert [g[0] for g in got] == ["press", "release"]
    assert got[0][1] == 10 and got[1][1] == 11


def test_reply_callback_skips_malformed_chunk_keeps_rest():
    class _Boom:
        def __init__(self, *a, **kw):
            raise ValueError("bad chunk")

    got = []
    cap = XRecordCapture(lambda *a: got.append(a))
    _stub_data_display(cap, {4: _Boom, 5: xevent.ButtonRelease,
                             6: xevent.MotionNotify})
    press = _binary_event(xevent.ButtonPress)        # parses via _Boom: raises
    release = _binary_event(xevent.ButtonRelease, state=256)
    cap._reply_callback(_reply(data=press + release))
    assert [g[0] for g in got] == ["release"]  # bad chunk skipped, not the rest


def test_consumer_exception_does_not_kill_stream():
    calls = []

    def boom(*a):
        calls.append(a)
        raise RuntimeError("consumer bug")

    cap = XRecordCapture(boom)
    _stub_data_display(cap)
    press = _binary_event(xevent.ButtonPress)
    cap._reply_callback(_reply(data=press + press))  # must not propagate
    assert len(calls) == 2


def test_on_died_fires_only_on_unexpected_death():
    died = []
    cap = XRecordCapture(lambda *a: None, on_died=lambda: died.append(1))
    cap._ctx = object()

    def _raise(ctx, cb):
        raise RuntimeError("conn lost")

    cap._data = SimpleNamespace(record_enable_context=_raise)
    cap._stopping = False
    cap._run()
    assert died == [1]
    died.clear()
    cap._stopping = True  # a normal stop() in flight: no death callback
    cap._run()
    assert died == []


def test_zombie_thread_does_not_touch_new_generation_state():
    # A thread stop() gave up on (forced-close timeout) finishing late must
    # not clear the NEW capture generation's flags or fire on_died.
    died = []
    cap = XRecordCapture(lambda *a: None, on_died=lambda: died.append(1))
    cap._ctx = object()

    def _raise(ctx, cb):
        raise RuntimeError("zombie finally exits")

    cap._data = SimpleNamespace(record_enable_context=_raise)
    cap._stopping = False
    cap._running = True
    cap._thread = SimpleNamespace()  # a NEWER generation's thread, not us
    cap._run()  # we are the zombie
    assert cap._running is True  # new generation untouched
    assert died == []


def test_start_lifecycle_and_clean_stream_end_fires_on_died(monkeypatch):
    # Exercises start() with stub displays: connection order (ctl, data),
    # context creation, running-before-start ordering, and the clean-end
    # (record_enable_context returns without stop()) death notification.
    import utils.xrecord_capture as xc

    class _StubCtl:
        def __init__(self):
            self.freed = []

        def has_extension(self, name):
            return name == "RECORD"

        def record_create_context(self, *a):
            return "CTX"

        def sync(self):
            pass

        def record_disable_context(self, ctx):
            pass

        def flush(self):
            pass

        def record_free_context(self, ctx):
            self.freed.append(ctx)

        def close(self):
            pass

    class _StubData:
        def record_enable_context(self, ctx, cb):
            return None  # clean stream end, no stop() in flight

        def close(self):
            pass

    made = []

    def fake_display():
        d = _StubCtl() if not made else _StubData()
        made.append(d)
        return d

    monkeypatch.setattr(xc.xdisplay, "Display", fake_display)
    died = threading.Event()
    cap = xc.XRecordCapture(lambda *a: None, on_died=died.set)
    assert cap.start() is True
    assert died.wait(2.0)  # clean end without stop() = unexpected death
    cap.stop()
    assert cap.is_running() is False
    assert made[0].freed == ["CTX"]


def test_stop_from_on_died_is_safe_and_cleans_up():
    # The natural consumer reaction to on_died is stop(); it runs ON the
    # capture thread, so the self-join must be skipped and cleanup must
    # still free the context and close both displays.
    freed, closed = [], []
    cap = XRecordCapture(lambda *a: None)
    cap._on_died = lambda: cap.stop()
    cap._ctx = "CTX"
    cap._ctl = SimpleNamespace(
        record_disable_context=lambda ctx: None,
        flush=lambda: None,
        record_free_context=lambda ctx: freed.append(ctx),
        close=lambda: closed.append("ctl"))

    def _raise(ctx, cb):
        raise RuntimeError("dead")

    cap._data = SimpleNamespace(record_enable_context=_raise,
                                close=lambda: closed.append("data"))
    cap._running = True
    cap._thread = threading.current_thread()  # we ARE the capture thread
    cap._run()
    assert freed == ["CTX"]
    assert "ctl" in closed and "data" in closed
    assert cap.is_running() is False
    assert cap._thread is None
