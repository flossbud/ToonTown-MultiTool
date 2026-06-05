from utils import win32_integrity
from utils.win32_integrity import Capability, classify_integrity, window_capability


def test_higher_target_is_blocked():
    assert classify_integrity(own_il=0x2000, target_il=0x3000) is Capability.BLOCKED_UIPI


def test_equal_target_is_ok():
    assert classify_integrity(own_il=0x3000, target_il=0x3000) is Capability.OK


def test_lower_target_is_ok():
    assert classify_integrity(own_il=0x3000, target_il=0x2000) is Capability.OK


def test_unreadable_own_or_target_is_unknown():
    assert classify_integrity(own_il=None, target_il=0x3000) is Capability.UNKNOWN
    assert classify_integrity(own_il=0x2000, target_il=None) is Capability.UNKNOWN


def test_window_capability_uses_injected_reader(monkeypatch):
    monkeypatch.setattr(win32_integrity, "_IS_WINDOWS", True)
    monkeypatch.setattr(win32_integrity, "_read_integrities",
                        lambda hwnd: (0x2000, 0x3000))
    assert window_capability(1234) is Capability.BLOCKED_UIPI


def test_window_capability_unknown_when_reader_returns_none(monkeypatch):
    monkeypatch.setattr(win32_integrity, "_IS_WINDOWS", True)
    monkeypatch.setattr(win32_integrity, "_read_integrities",
                        lambda hwnd: (0x2000, None))
    assert window_capability(1234) is Capability.UNKNOWN


def test_window_capability_is_ok_off_windows(monkeypatch):
    monkeypatch.setattr(win32_integrity, "_IS_WINDOWS", False)
    monkeypatch.setattr(win32_integrity, "_read_integrities",
                        lambda hwnd: (_ for _ in ()).throw(AssertionError("called")))
    assert window_capability(1234) is Capability.OK


def test_window_capability_unknown_on_reader_exception(monkeypatch):
    monkeypatch.setattr(win32_integrity, "_IS_WINDOWS", True)
    def boom(hwnd):
        raise OSError("denied")
    monkeypatch.setattr(win32_integrity, "_read_integrities", boom)
    assert window_capability(1234) is Capability.UNKNOWN


from utils.win32_integrity import WindowCapabilityCache


class _FakeClock:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t


def test_cache_memoizes_within_ttl():
    calls = []
    def reader(hwnd):
        calls.append(hwnd)
        return Capability.BLOCKED_UIPI
    c = WindowCapabilityCache(reader=reader, pid_of=lambda h: 42, ttl=3.0, clock=_FakeClock())
    assert c.get(1) is Capability.BLOCKED_UIPI
    assert c.get(1) is Capability.BLOCKED_UIPI
    assert calls == [1]


def test_cache_refreshes_after_ttl():
    seq = iter([Capability.BLOCKED_UIPI, Capability.OK])
    clock = _FakeClock()
    c = WindowCapabilityCache(reader=lambda h: next(seq), pid_of=lambda h: 42, ttl=3.0, clock=clock)
    assert c.get(1) is Capability.BLOCKED_UIPI
    clock.t += 4.0
    assert c.get(1) is Capability.OK


def test_cache_invalidates_on_pid_change():
    seq = iter([Capability.BLOCKED_UIPI, Capability.OK])
    pids = iter([42, 99])
    c = WindowCapabilityCache(reader=lambda h: next(seq), pid_of=lambda h: next(pids), ttl=3.0, clock=_FakeClock())
    assert c.get(1) is Capability.BLOCKED_UIPI
    assert c.get(1) is Capability.OK


def test_peek_never_calls_reader():
    calls = []
    c = WindowCapabilityCache(reader=lambda h: calls.append(h) or Capability.OK,
                              pid_of=lambda h: 1, ttl=3.0, clock=_FakeClock())
    assert c.peek(1) is Capability.UNKNOWN   # never refreshed -> UNKNOWN, reader untouched
    assert calls == []


def test_get_populates_then_peek_hits():
    calls = []
    c = WindowCapabilityCache(reader=lambda h: calls.append(h) or Capability.BLOCKED_UIPI,
                              pid_of=lambda h: 1, ttl=3.0, clock=_FakeClock())
    assert c.get(1) is Capability.BLOCKED_UIPI
    assert c.peek(1) is Capability.BLOCKED_UIPI
    assert calls == [1]


def test_peek_unknown_after_pid_change():
    pids = iter([42, 99]).__next__
    c = WindowCapabilityCache(reader=lambda h: Capability.BLOCKED_UIPI,
                              pid_of=lambda h: pids(), ttl=3.0, clock=_FakeClock())
    assert c.get(1) is Capability.BLOCKED_UIPI
    assert c.peek(1) is Capability.UNKNOWN   # pid changed -> snapshot stale -> UNKNOWN
