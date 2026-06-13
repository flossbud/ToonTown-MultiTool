"""Unit tests for MacOSBackend using a fake Quartz (no real PyObjC runs)."""
from __future__ import annotations

import pytest

from utils.macos_backend import MacOSBackend, SPIKE_EVENT_TAG


class _FakeQuartz:
    """Records CGEvent posts/flags; no real PyObjC."""

    kCGEventSourceUserData = "kCGEventSourceUserData"
    kCGEventSourceStateCombinedSessionState = 99

    def __init__(self):
        self.posts = []  # list of (pid, ev)
        self.flags = []  # list of (ev, flags)

    def CGEventSourceCreate(self, state):
        return ("source", state)

    def CGEventCreateKeyboardEvent(self, source, vk, down):
        return {"source": source, "vk": vk, "down": bool(down)}

    def CGEventSetIntegerValueField(self, ev, field, value):
        ev[field] = value

    def CGEventSetFlags(self, ev, flags):
        ev["flags"] = flags
        self.flags.append((ev, flags))

    def CGEventPostToPid(self, pid, ev):
        self.posts.append((pid, ev))


def _backend_with_fake(monkeypatch, fake):
    be = MacOSBackend()
    monkeypatch.setattr(be, "_quartz", lambda: fake)
    be.connect()
    return be


def test_send_keydown_valid_pid(monkeypatch):
    fake = _FakeQuartz()
    be = _backend_with_fake(monkeypatch, fake)
    monkeypatch.setattr(be, "_refresh", lambda: {"11": (4242, "com.ttr")})

    assert be.send_keydown("11", "w") is True
    assert len(fake.posts) == 1
    pid, ev = fake.posts[0]
    assert pid == 4242
    assert ev["vk"] == 0x0D
    assert ev["down"] is True
    assert ev[fake.kCGEventSourceUserData] == SPIKE_EVENT_TAG


def test_send_key_with_shift(monkeypatch):
    fake = _FakeQuartz()
    be = _backend_with_fake(monkeypatch, fake)
    monkeypatch.setattr(be, "_refresh", lambda: {"11": (4242, "com.ttr")})

    assert be.send_key("11", "w", ["Shift_L"]) is True
    assert len(fake.posts) == 2  # down + up
    downs = [ev["down"] for _, ev in fake.posts]
    assert downs == [True, False]
    for _, ev in fake.posts:
        assert ev["flags"] == 0x00020000


def test_unknown_keysym(monkeypatch):
    fake = _FakeQuartz()
    be = _backend_with_fake(monkeypatch, fake)
    monkeypatch.setattr(be, "_refresh", lambda: {"11": (4242, "com.ttr")})

    assert be.send_keydown("11", "F24_nope") is False
    assert fake.posts == []


def test_stale_target(monkeypatch):
    fake = _FakeQuartz()
    be = _backend_with_fake(monkeypatch, fake)
    monkeypatch.setattr(be, "_refresh", lambda: {})  # nothing valid

    assert be.send_keydown("11", "w") is False
    assert fake.posts == []


def test_bundle_mismatch_and_match(monkeypatch):
    fake = _FakeQuartz()
    be = _backend_with_fake(monkeypatch, fake)
    monkeypatch.setattr(be, "_refresh", lambda: {"11": (101, "com.evil")})

    assert be._resolve_pid("11", expected_bundle="com.ttr") is None
    assert be._resolve_pid("11", expected_bundle="com.evil") == 101
    assert be._resolve_pid("11") == 101  # no expectation -> returns pid


def test_mouse_methods_return_false():
    be = MacOSBackend()
    assert be.send_button_press("11", 1, 2) is False
    assert be.send_button_release("11", 1, 2) is False
    assert be.send_motion("11", 1, 2) is False


def test_module_imports_without_pyobjc():
    import sys
    import utils.macos_backend  # noqa: F401

    # No PyObjC modules should be imported merely by importing the backend.
    assert "Quartz" not in sys.modules
