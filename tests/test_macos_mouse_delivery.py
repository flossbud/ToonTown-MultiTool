"""Pure-helper tests (no PyObjC) + macOS-gated native smoke tests for the mouse
delivery engine."""
import sys

import pytest

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


class _FakePort:
    """Records every native call so engine orchestration is testable without PyObjC."""
    def __init__(self, record_status=0, fail_kinds=None):
        self.records = []   # (psn, record_bytes)
        self.posts = []     # (pid, ev-dict)
        self._status = record_status
        self._fail_kinds = set(fail_kinds or ())

    def make_event(self, kind, click_count, window_number):
        return {"kind": kind, "cc": click_count, "wid": window_number,
                "fields": {}, "win": None, "screen": None, "tag": None}

    def set_public_field(self, ev, field, value):  ev["fields"][("pub", field)] = value
    def set_private_field(self, ev, field, value): ev["fields"][("priv", field)] = value
    def set_window_location(self, ev, pt): ev["win"] = pt
    def set_location(self, ev, pt):        ev["screen"] = pt
    def set_source_user_data(self, ev, tag): ev["tag"] = tag

    def post(self, pid, ev):
        if ev["kind"] in self._fail_kinds:
            raise RuntimeError("boom")
        self.posts.append((pid, ev))

    def post_record(self, psn, rec):
        self.records.append((psn, rec))
        return self._status

    def resolve_psn(self, wid):
        return b"PSN" + bytes([wid & 0xFF])

    def resolve_owner(self, wid):
        return 9000 + wid


def _eng(port, ledger=None):
    return d.MacOSMouseDelivery(port=port, ledger=ledger)


def test_press_posts_keyflip_then_move_then_down(monkeypatch):
    monkeypatch.setattr(d.time, "sleep", lambda *_a, **_k: None)
    p = _FakePort()
    assert _eng(p).press(4242, 77, b"PSN0", (100.0, 50.0), (1100.0, 80.0)) is True
    assert [r[1] for r in p.records] == [
        d.build_activate_record(77), d.make_key_record(77, 0x01), d.make_key_record(77, 0x02)]
    assert [ev["kind"] for _, ev in p.posts] == ["move", "down"]   # NOT up
    move = p.posts[0][1]
    assert move["win"] == (100.0, 50.0)
    assert move["screen"] == (1100.0, 80.0)
    assert move["tag"] == d.SPIKE_EVENT_TAG
    assert move["fields"][("priv", 40)] == 4242
    assert move["fields"][("priv", 91)] == 77


def test_nonzero_record_status_is_sticky(monkeypatch):
    monkeypatch.setattr(d.time, "sleep", lambda *_a, **_k: None)
    eng = _eng(_FakePort(record_status=1))
    assert eng.press(4242, 77, b"PSN0", (1, 1), (1, 1)) is False
    assert eng.available is False


def test_down_failure_posts_compensating_up(monkeypatch):
    monkeypatch.setattr(d.time, "sleep", lambda *_a, **_k: None)
    p = _FakePort(fail_kinds={"down"})
    assert _eng(p).press(4242, 77, b"PSN0", (1, 1), (1, 1)) is False
    assert [ev["kind"] for _, ev in p.posts] == ["move", "up"]   # compensating up


def test_motion_and_release_skip_keyflip(monkeypatch):
    monkeypatch.setattr(d.time, "sleep", lambda *_a, **_k: None)
    p = _FakePort()
    eng = _eng(p)
    assert eng.motion(1, 2, b"P", (1, 1), (2, 2), dragging=True) is True
    assert eng.motion(1, 2, b"P", (1, 1), (2, 2), dragging=False) is True
    assert eng.release(1, 2, b"P", (1, 1), (2, 2)) is True
    assert [ev["kind"] for _, ev in p.posts] == ["dragged", "move", "up"]
    assert p.records == []   # no key-flip on motion/release


def test_unavailable_without_pyobjc():
    eng = d.MacOSMouseDelivery(port=None)   # import Quartz fails on the test host
    assert eng.available is False
    assert eng.press(1, 2, b"P", (1, 1), (2, 2)) is False


def test_engine_records_posts_into_shared_ledger(monkeypatch):
    monkeypatch.setattr(d.time, "sleep", lambda *_a, **_k: None)
    led = d.EchoLedger(ttl=0.25)
    eng = _eng(_FakePort(), ledger=led)
    assert eng.press(4242, 77, b"PSN0", (100.0, 50.0), (1100.0, 80.0)) is True
    # the move(5) and down(1) screen signatures are now "ours" (echo-recognizable)
    assert led.matches(5, 1100.0, 80.0) is True
    assert led.matches(1, 1100.0, 80.0) is True
    assert led.matches(2, 1100.0, 80.0) is False   # no up was posted by press


def test_abi_diagnostics_logged_once(monkeypatch):
    monkeypatch.setattr(d.time, "sleep", lambda *_a, **_k: None)
    d._DIAG_LOG.clear()
    eng = _eng(_FakePort(record_status=1))   # key-flip records fail -> sticky fault
    assert eng.press(4242, 77, b"PSN0", (1, 1), (1, 1)) is False
    assert eng.press(4242, 77, b"PSN0", (1, 1), (1, 1)) is False   # second fault
    assert len(d._DIAG_LOG) == 1            # logged exactly ONCE
    assert "phase=record" in d._DIAG_LOG[0]


def test_resolve_owner_delegates_to_port():
    eng = _eng(_FakePort())
    assert eng.resolve_owner(77) == 9077


# ── macOS-gated native smoke tests ──────────────────────────────────────────────
# Run on the dev/test host where PyObjC is present; SKIPPED on Linux/Windows CI. They
# catch private-ABI regressions the _FakePort orchestration tests cannot (a renamed or
# removed SkyLight symbol, a broken ctypes signature, the NSEvent->CGEvent bridge, the
# _CGPoint by-value marshalling). No event is ever POSTED to any process.
_darwin_only = pytest.mark.skipif(sys.platform != "darwin", reason="native SkyLight/PyObjC is macOS-only")


@_darwin_only
def test_native_loads_all_skylight_symbols():
    sky = d._load_skylight()
    assert sky is not None
    assert set(sky) == set(d._SKYLIGHT_SYMBOLS)        # every declared symbol resolved
    assert all(callable(fn) for fn in sky.values())


@_darwin_only
def test_native_port_builds_and_stamps_event():
    import Quartz
    port = d._NativePort(Quartz, d._load_skylight())
    ev = port.make_event("move", 0, 0)                 # NSEvent -> CGEvent bridge
    assert ev is not None
    # every stamping path runs against a real CGEvent without raising (ctypes shapes OK)
    for field, value, via_private in d.mouse_event_fields(4242, 77):
        (port.set_private_field if via_private else port.set_public_field)(ev, field, value)
    port.set_window_location(ev, (10.0, 20.0))         # _CGPoint by-value marshalling
    port.set_location(ev, (100.0, 200.0))
    port.set_source_user_data(ev, d.SPIKE_EVENT_TAG)


@_darwin_only
def test_native_resolve_psn_invalid_window_is_none():
    import Quartz
    port = d._NativePort(Quartz, d._load_skylight())
    assert port.resolve_psn(0x7FFFFFFF) is None        # bogus wid -> no owner -> None, no crash


@_darwin_only
def test_engine_available_and_lazy_loads_on_macos():
    eng = d.MacOSMouseDelivery()                       # omit port -> lazy-load the native port
    assert eng.available is True
    assert eng.resolve_psn(0x7FFFFFFF) is None         # graceful on a bogus wid
