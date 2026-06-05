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
