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
        self.raise_on_post = False
        self.preflight_result = True   # CGPreflightPostEventAccess return
        self.preflight_calls = 0

    def CGPreflightPostEventAccess(self):
        self.preflight_calls += 1
        return self.preflight_result

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
        if self.raise_on_post:
            raise RuntimeError("boom")
        self.posts.append((pid, ev))


def _backend_with_fake(monkeypatch, fake):
    be = MacOSBackend()
    monkeypatch.setattr(be, "_quartz", lambda: fake)
    be.connect()
    return be


def test_has_post_access_reflects_preflight(monkeypatch):
    fake = _FakeQuartz()
    be = _backend_with_fake(monkeypatch, fake)
    fake.preflight_result = True
    assert be.has_post_access() is True
    # Cached within the TTL: a flip is not seen until the cache expires, and the
    # preflight is not re-called on every query (avoids a per-keystroke syscall).
    fake.preflight_result = False
    assert be.has_post_access() is True       # still cached True
    assert fake.preflight_calls == 1
    # Force a re-check (simulate cache expiry) -> now reflects the denial.
    be._access = {"t": -1.0, "ok": True}
    assert be.has_post_access() is False


def test_has_post_access_fails_open_on_check_error(monkeypatch):
    fake = _FakeQuartz()
    be = _backend_with_fake(monkeypatch, fake)
    be._access = {"t": -1.0, "ok": True}

    def _raise():
        raise RuntimeError("preflight blew up")

    monkeypatch.setattr(fake, "CGPreflightPostEventAccess", _raise)
    # A check ERROR (not a definitive denial) must not disable a working setup.
    assert be.has_post_access() is True


def test_has_post_access_true_when_symbol_missing(monkeypatch):
    # Older macOS without CGPreflightPostEventAccess -> best-effort access-OK.
    class _NoPreflight:
        kCGEventSourceStateCombinedSessionState = 99

        def CGEventSourceCreate(self, state):
            return ("source", state)

    fake = _NoPreflight()
    be = MacOSBackend()
    monkeypatch.setattr(be, "_quartz", lambda: fake)
    be._access = {"t": -1.0, "ok": True}
    assert be.has_post_access() is True


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


def test_send_key_posts_down_then_up_same_pid(monkeypatch):
    fake = _FakeQuartz()
    be = _backend_with_fake(monkeypatch, fake)
    monkeypatch.setattr(be, "_refresh", lambda: {"11": (4242, "com.ttr")})

    # Count _resolve_pid invocations: send_key must resolve EXACTLY once.
    calls = {"n": 0}
    real_resolve = be._resolve_pid

    def counting_resolve(wid):
        calls["n"] += 1
        return real_resolve(wid)

    monkeypatch.setattr(be, "_resolve_pid", counting_resolve)

    assert be.send_key("11", "w", ["Shift_L"]) is True
    assert calls["n"] == 1  # resolved ONCE
    assert len(fake.posts) == 2  # down + up
    pids = [pid for pid, _ in fake.posts]
    assert pids == [4242, 4242]  # same pid
    downs = [ev["down"] for _, ev in fake.posts]
    assert downs == [True, False]
    for _, ev in fake.posts:
        assert ev["flags"] == 0x00020000


def test_send_always_sets_flags_even_when_zero(monkeypatch):
    fake = _FakeQuartz()
    be = _backend_with_fake(monkeypatch, fake)
    monkeypatch.setattr(be, "_refresh", lambda: {"11": (4242, "com.ttr")})

    # Unmodified send: must still clear ambient modifiers via a flags-0 call.
    assert be.send_keydown("11", "w") is True
    assert fake.flags, "CGEventSetFlags was never called"
    assert any(flags == 0 for _, flags in fake.flags)


def test_unknown_keysym(monkeypatch):
    fake = _FakeQuartz()
    be = _backend_with_fake(monkeypatch, fake)
    monkeypatch.setattr(be, "_refresh", lambda: {"11": (4242, "com.ttr")})

    assert be.send_keydown("11", "F24_nope") is False
    assert fake.posts == []


def test_stale_target_resolve_none(monkeypatch):
    fake = _FakeQuartz()
    be = _backend_with_fake(monkeypatch, fake)
    monkeypatch.setattr(be, "_refresh", lambda: {})  # nothing valid

    assert be.send_keydown("11", "w") is False
    assert fake.posts == []


def test_refresh_failure_yields_no_targets(monkeypatch):
    fake = _FakeQuartz()
    be = _backend_with_fake(monkeypatch, fake)

    import utils.macos_discovery as disc

    def boom():
        raise RuntimeError("enumeration failed")

    monkeypatch.setattr(disc, "_enumerate_game_windows", boom)

    # _refresh must swallow the error and yield {} (never propagate).
    assert be._refresh() == {}
    assert be.send_keydown("11", "w") is False
    assert fake.posts == []


def test_trusted_bundle_reuse_caught(monkeypatch):
    fake = _FakeQuartz()
    be = _backend_with_fake(monkeypatch, fake)

    monkeypatch.setattr(be, "_refresh", lambda: {"11": (101, "com.ttr")})
    assert be._resolve_pid("11") == 101  # first sight records com.ttr

    # Same window id now resolves to a different bundle -> identity reuse.
    monkeypatch.setattr(be, "_refresh", lambda: {"11": (101, "com.evil")})
    assert be._resolve_pid("11") is None  # reuse caught


def test_disappeared_wid_clears_trust(monkeypatch):
    fake = _FakeQuartz()
    be = _backend_with_fake(monkeypatch, fake)

    monkeypatch.setattr(be, "_refresh", lambda: {"11": (101, "com.ttr")})
    assert be._resolve_pid("11") == 101
    assert "11" in be._trusted

    # Window disappears -> None and trust cleared.
    monkeypatch.setattr(be, "_refresh", lambda: {})
    assert be._resolve_pid("11") is None
    assert "11" not in be._trusted


def test_post_exception_returns_false(monkeypatch):
    fake = _FakeQuartz()
    fake.raise_on_post = True
    be = _backend_with_fake(monkeypatch, fake)
    monkeypatch.setattr(be, "_refresh", lambda: {"11": (4242, "com.ttr")})

    # CGEventPostToPid raises -> _post_to_pid must catch and return False.
    assert be.send_keydown("11", "w") is False
    assert fake.posts == []  # nothing recorded (raised before append)


def test_mouse_methods_return_false(monkeypatch):
    # Monkeypatch _refresh so the mouse methods never reach the real
    # Quartz/SkyLight layer (which would pollute sys.modules for the
    # test_module_imports_without_pyobjc assertion that follows).
    be = MacOSBackend()
    monkeypatch.setattr(be, "_refresh", lambda: {})   # no valid game windows
    assert be.send_button_press("11", 1, 2, 3, 4) is False
    assert be.send_button_release("11", 1, 2, 3, 4) is False
    assert be.send_motion("11", 1, 2, 3, 4) is False


def test_disconnect_clears_cache_and_trust(monkeypatch):
    fake = _FakeQuartz()
    be = _backend_with_fake(monkeypatch, fake)
    monkeypatch.setattr(be, "_refresh", lambda: {"11": (101, "com.ttr")})
    be._resolve_pid("11")
    assert be._trusted

    be.disconnect()
    assert be._trusted == {}
    assert be._cache["valid"] == {}
    assert be._source is None


def test_module_imports_without_pyobjc():
    import sys
    import utils.macos_backend  # noqa: F401

    # No PyObjC modules should be imported merely by importing the backend.
    assert "Quartz" not in sys.modules
