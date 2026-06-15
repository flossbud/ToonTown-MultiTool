"""Pure-helper tests for the macOS mouse capture (no PyObjC)."""
import utils.macos_mouse_capture as c


def test_mask_for():
    assert c.mask_for(set()) == 0
    assert c.mask_for({1}) == 0x100
    assert c.mask_for({2}) == 0x200                # Button2Mask (middle)
    assert c.mask_for({1, 3}) == 0x100 | 0x400


def test_classify_event():
    # full CGEventType mapping (left/right/other x down/up/drag + move + unknown)
    assert c.classify_event(1) == ("down", 1)    # LeftMouseDown
    assert c.classify_event(2) == ("up", 1)      # LeftMouseUp
    assert c.classify_event(5) == ("move", None) # MouseMoved
    assert c.classify_event(6) == ("move", 1)    # LeftMouseDragged
    assert c.classify_event(3) == ("down", 3)    # RightMouseDown
    assert c.classify_event(4) == ("up", 3)      # RightMouseUp
    assert c.classify_event(7) == ("move", 3)    # RightMouseDragged
    assert c.classify_event(25) == ("down", 2)   # OtherMouseDown -> middle
    assert c.classify_event(26) == ("up", 2)     # OtherMouseUp
    assert c.classify_event(27) == ("move", 2)   # OtherMouseDragged
    assert c.classify_event(999) == (None, None)


def test_button_state_x_semantics():
    s = c.ButtonState()
    assert s.on_down(1) == 0          # press EXCLUDES itself
    assert s.on_move() == 0x100       # held carries
    assert s.on_up(1) == 0x100        # release INCLUDES itself
    assert s.on_move() == 0           # cleared after release


def test_echo_guard_marker_and_own_pid():
    g = c.EchoGuard(c.EchoLedger(), own_pid=999, now=lambda: 0.0)
    assert g.is_synthetic(5, 10, 10, marker=c.SPIKE_EVENT_TAG, src_pid=None) is True
    assert g.is_synthetic(5, 10, 10, marker=0, src_pid=999) is True
    assert g.is_synthetic(5, 10, 10, marker=0, src_pid=None) is False


def test_echo_guard_signature_match_via_shared_ledger():
    t = [0.0]
    led = c.EchoLedger(ttl=0.25)
    g = c.EchoGuard(led, own_pid=1, now=lambda: t[0])
    led.record(1, 100, 50, now=t[0])                                    # the delivery engine's post
    assert g.is_synthetic(1, 101, 50, marker=0, src_pid=None) is True   # round(x/2) match, live
    t[0] = 0.3                                                          # past the ledger TTL
    assert g.is_synthetic(1, 101, 50, marker=0, src_pid=None) is False


def test_circuit_breaker_trips_only_on_markerless_echoes():
    t = [0.0]
    led = c.EchoLedger(ttl=10.0)
    g = c.EchoGuard(led, own_pid=1, now=lambda: t[0])
    # Correctly-MARKED echoes are filtered but never counted -> never trip.
    for _ in range(c.ECHO_TRIP + 5):
        assert g.is_synthetic(1, 100, 50, marker=c.SPIKE_EVENT_TAG, src_pid=None) is True
    assert g.tripped is False
    # MARKER-STRIPPED echoes (signature match, marker absent) DO count -> trip + sticky.
    led.record(1, 100, 50, now=0.0)
    for _ in range(c.ECHO_TRIP + 1):
        assert g.is_synthetic(1, 100, 50, marker=0, src_pid=None) is True
    assert g.tripped is True
    t[0] = 100.0                       # long after the window
    assert g.tripped is True           # sticky


def test_breaker_constants():
    assert c.ECHO_TRIP == 24
    assert c.ECHO_WINDOW_S == 0.5


def test_circuit_breaker_evicts_hits_outside_window():
    # markerless+signature-matched hits spread > ECHO_WINDOW_S apart must NOT accumulate
    # (the sliding window evicts old hits), so the breaker never trips.
    t = [0.0]
    led = c.EchoLedger(ttl=10_000.0)
    g = c.EchoGuard(led, own_pid=1, now=lambda: t[0])
    for i in range(c.ECHO_TRIP + 5):
        t[0] = i * (c.ECHO_WINDOW_S + 0.1)     # each hit is past the prior's window
        led.record(1, 100, 50, now=t[0])        # keep the signature live in the ledger
        assert g.is_synthetic(1, 100, 50, marker=0, src_pid=None) is True
    assert g.tripped is False


def test_echo_guard_own_pid_none():
    g = c.EchoGuard(c.EchoLedger(), own_pid=None, now=lambda: 0.0)
    # own_pid None: the PID arm never filters a real event...
    assert g.is_synthetic(5, 10, 10, marker=0, src_pid=12345) is False
    # ...but the marker arm still filters our own posts.
    assert g.is_synthetic(5, 10, 10, marker=c.SPIKE_EVENT_TAG, src_pid=12345) is True


def test_echo_guard_ttl_inclusive_boundary():
    t = [0.0]
    led = c.EchoLedger(ttl=0.25)
    g = c.EchoGuard(led, own_pid=1, now=lambda: t[0])
    led.record(1, 100, 50, now=0.0)                                      # expires at 0.25
    t[0] = 0.25
    assert g.is_synthetic(1, 100, 50, marker=0, src_pid=None) is True    # inclusive (exp >= t)
    t[0] = 0.2500001
    assert g.is_synthetic(1, 100, 50, marker=0, src_pid=None) is False


from time import monotonic, sleep


class _FakeNative:
    def __init__(self, on_tap_event, on_ready, on_died):
        self.on_tap_event = on_tap_event
        self.on_ready = on_ready
        self.on_died = on_died
        self.started = self.stopped = False
        self._alive = False
        self.start_result = True

    def start(self):
        if not self.start_result:
            return False
        self.started = True
        self._alive = True
        self.on_ready()          # synchronous readiness for the test
        return True

    def stop(self):
        self.stopped = True
        self._alive = False

    def is_alive(self):
        return self._alive

    def die(self):               # simulate an unexpected runloop death
        self._alive = False
        self.on_died()


def _wait(pred, timeout=1.0):
    end = monotonic() + timeout
    while monotonic() < end:
        if pred():
            return True
        sleep(0.005)
    return pred()


def _capture():
    events, died, holder = [], [], {}
    led = c.EchoLedger(ttl=10.0)
    holder["led"] = led
    def factory(on_tap, on_ready, on_died):
        holder["n"] = _FakeNative(on_tap, on_ready, on_died)
        return holder["n"]
    cap = c.MacOSMouseCapture(lambda *a: events.append(a),
                              on_died=lambda: died.append(True),
                              ledger=led, own_pid=4242, native_factory=factory)
    return cap, events, died, holder


def test_start_dispatch_and_clean_stop():
    cap, events, died, holder = _capture()
    assert cap.start() is True
    assert cap.is_running() is True
    n = holder["n"]
    n.on_tap_event(1, 100.0, 50.0, 0, 999)   # LeftDown (foreign pid)
    n.on_tap_event(2, 100.0, 50.0, 0, 999)   # LeftUp
    n.on_tap_event(5, 110.0, 60.0, 0, 999)   # Move
    assert _wait(lambda: len(events) >= 3)
    assert [e[0] for e in events] == ["press", "release", "motion"]
    assert events[0][3] == 0       # press EXCLUDES Button1
    assert events[1][3] == 0x100   # release INCLUDES Button1
    cap.stop()
    assert cap.is_running() is False
    assert died == []              # clean stop does NOT fire on_died


def test_synthetic_events_filtered():
    cap, events, died, holder = _capture()
    cap.start()
    holder["n"].on_tap_event(1, 1.0, 1.0, c.SPIKE_EVENT_TAG, 4242)  # marker + own pid
    assert _wait(lambda: len(events) > 0, timeout=0.2) is False
    cap.stop()


def test_marked_echoes_never_trip_breaker():
    cap, events, died, holder = _capture()
    cap.start()
    # correctly-MARKED echoes are filtered but do NOT count toward the breaker
    for _ in range(c.ECHO_TRIP + 5):
        holder["n"].on_tap_event(5, 1.0, 1.0, c.SPIKE_EVENT_TAG, None)
    assert _wait(lambda: died == [True], timeout=0.2) is False
    assert cap.is_running() is True
    cap.stop()


def test_echo_breaker_trips_on_markerless_echoes_and_fires_on_died():
    cap, events, died, holder = _capture()
    cap.start()
    holder["led"].record(5, 1.0, 1.0)            # signature of a recent post (markerless echo target)
    for _ in range(c.ECHO_TRIP + 1):
        holder["n"].on_tap_event(5, 1.0, 1.0, 0, None)   # markerless + signature match -> counts
    assert _wait(lambda: died == [True])
    assert cap.is_running() is False


def test_native_death_fires_on_died_once():
    cap, events, died, holder = _capture()
    cap.start()
    holder["n"].die()
    assert _wait(lambda: died == [True])
    assert cap.is_running() is False


def test_start_failure_returns_false():
    events = []
    def factory(on_tap, on_ready, on_died):
        n = _FakeNative(on_tap, on_ready, on_died)
        n.start_result = False
        return n
    cap = c.MacOSMouseCapture(lambda *a: events.append(a), native_factory=factory)
    assert cap.start() is False
    assert cap.is_running() is False


def test_enqueue_coalesces_consecutive_motion():
    cap, events, died, holder = _capture()   # dispatcher not started -> queue inspectable
    cap._enqueue(("motion", 1, 1, 0, 0))
    cap._enqueue(("motion", 2, 2, 0, 0))
    cap._enqueue(("press", 3, 3, 0x100, 0))
    cap._enqueue(("motion", 4, 4, 0, 0))
    assert list(cap._queue) == [("motion", 2, 2, 0, 0),
                                ("press", 3, 3, 0x100, 0),
                                ("motion", 4, 4, 0, 0)]
