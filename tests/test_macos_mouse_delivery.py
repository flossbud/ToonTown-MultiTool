"""Pure-helper tests for the macOS mouse delivery engine (no PyObjC)."""
import utils.macos_mouse_delivery as d


def test_activate_record_bytes():
    rec = d.build_activate_record(0x1234)
    assert len(rec) == 0xF8
    assert rec[0x04] == 0xF8
    assert rec[0x08] == 0x0D
    assert rec[0x3C:0x40] == (0x1234).to_bytes(4, "little")
    assert rec[0x8A] == 0x01
    # everything else zero
    assert sum(rec) == 0xF8 + 0x0D + sum((0x1234).to_bytes(4, "little")) + 0x01


def test_make_key_record_bytes():
    rec = d.make_key_record(0x1234, 0x02)
    # byte-for-byte: catches any stray nonzero byte outside the asserted offsets
    expected = bytearray(0xF8)
    expected[0x04] = 0xF8
    expected[0x08] = 0x02
    expected[0x3A] = 0x10
    expected[0x3C:0x40] = (0x1234).to_bytes(4, "little")
    for i in range(0x20, 0x30):
        expected[i] = 0xFF
    assert rec == bytes(expected)
    assert len(rec) == 0xF8


def test_mouse_event_fields_proven_values():
    f = d.mouse_event_fields(4242, 77)
    assert (1, 1, False) in f      # ClickState
    assert (3, 0, False) in f      # ButtonNumber left
    assert (7, 3, False) in f      # Subtype
    assert (40, 4242, True) in f   # target PID (private)
    assert (91, 77, True) in f     # window id (private)
    assert (92, 77, True) in f     # window id (private)


def test_event_kinds_and_click_count():
    assert d.EVENT_KINDS["move"][0] == 5
    assert d.EVENT_KINDS["down"][0] == 1
    assert d.EVENT_KINDS["up"][0] == 2
    assert d.EVENT_KINDS["dragged"][0] == 6
    assert d.click_count_for("move") == 0
    assert d.click_count_for("down") == 1
    assert d.click_count_for("dragged") == 1


def test_echo_ledger_records_and_matches_within_ttl():
    led = d.EchoLedger(ttl=0.25)
    led.record(1, 1100.0, 80.0, now=100.0)             # a posted down's screen point
    assert led.matches(1, 1101.0, 81.0, now=100.1) is True    # bucketed (/2) + live
    assert led.matches(1, 1101.0, 81.0, now=100.4) is False   # expired (>0.25s TTL)
    assert led._sigs == {}                                    # matches() actually evicted it
    assert led.matches(5, 1100.0, 80.0, now=100.0) is False   # different event type


def test_echo_ledger_record_evicts_expired():
    # record() must bound the dict even if matches() is never called (delivery posting
    # while capture is idle).
    led = d.EchoLedger(ttl=0.25)
    led.record(1, 10.0, 20.0, now=100.0)               # entry A, expires at 100.25
    led.record(2, 30.0, 40.0, now=100.5)               # later record() evicts the stale A
    assert led._sig(1, 10.0, 20.0) not in led._sigs
    assert led._sig(2, 30.0, 40.0) in led._sigs
