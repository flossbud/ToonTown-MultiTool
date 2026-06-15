"""Pure-helper tests for the macOS mouse capture (no PyObjC)."""
import utils.macos_mouse_capture as c


def test_mask_for():
    assert c.mask_for(set()) == 0
    assert c.mask_for({1}) == 0x100
    assert c.mask_for({1, 3}) == 0x100 | 0x400


def test_classify_event():
    assert c.classify_event(1) == ("down", 1)    # LeftMouseDown
    assert c.classify_event(2) == ("up", 1)      # LeftMouseUp
    assert c.classify_event(5) == ("move", None) # MouseMoved
    assert c.classify_event(6) == ("move", 1)    # LeftMouseDragged
    assert c.classify_event(3) == ("down", 3)    # RightMouseDown
    assert c.classify_event(25) == ("down", 2)   # OtherMouseDown -> middle
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
