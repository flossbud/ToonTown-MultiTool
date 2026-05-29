"""Unit tests for services.sleep_inhibitor.SleepInhibitor.

All OS access (D-Bus session/system buses, Win32 kernel32, fd close) is
reached through module-level seams that these tests monkeypatch, so no real
bus or Win32 call is ever made.
"""

from types import SimpleNamespace

import pytest

import services.sleep_inhibitor as si


# ── Fakes ────────────────────────────────────────────────────────────────
class FakeProxy:
    def __init__(self, name, path, rec):
        self._name = name
        self._path = path
        self._rec = rec

    def Inhibit(self, *args, **kwargs):
        self._rec["inhibit"].append((self._name, args, kwargs))
        if "portal" in self._name:
            return "/portal/request/1"
        if "ScreenSaver" in self._name:
            return 42
        if "login1" in self._name:
            return SimpleNamespace(take=lambda: 7)
        return None

    def UnInhibit(self, *args, **kwargs):
        self._rec["uninhibit"].append((self._name, args, kwargs))

    def Close(self, *args, **kwargs):
        self._rec["close"].append((self._name, self._path, kwargs))


class FakeBus:
    def __init__(self, rec, fail_names=()):
        self._rec = rec
        self._fail = set(fail_names)

    def get_object(self, name, path):
        if name in self._fail:
            raise RuntimeError(f"unreachable: {name}")
        return FakeProxy(name, path, self._rec)


@pytest.fixture
def rec():
    return {"inhibit": [], "uninhibit": [], "close": [], "closed_fds": []}


def test_windows_acquire_sets_system_and_display_flags(monkeypatch, rec):
    calls = []
    monkeypatch.setattr(si, "_is_windows", lambda: True)
    monkeypatch.setattr(
        si, "_kernel32",
        lambda: SimpleNamespace(
            SetThreadExecutionState=lambda flags: calls.append(flags)
        ),
    )
    inh = si.SleepInhibitor()
    tier = inh.acquire()
    assert tier == "windows"
    # ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
    assert calls == [0x80000000 | 0x00000001 | 0x00000002]
    inh.release()
    # release clears with ES_CONTINUOUS only
    assert calls[-1] == 0x80000000
    assert inh.is_active() is False


def test_acquire_is_idempotent(monkeypatch):
    monkeypatch.setattr(si, "_is_windows", lambda: True)
    calls = []
    monkeypatch.setattr(
        si, "_kernel32",
        lambda: SimpleNamespace(
            SetThreadExecutionState=lambda flags: calls.append(flags)
        ),
    )
    inh = si.SleepInhibitor()
    assert inh.acquire() == "windows"
    assert inh.acquire() == "windows"  # second call holds the same lock
    assert len(calls) == 1  # only acquired once


def test_release_runs_all_thunks_even_if_one_raises(monkeypatch):
    monkeypatch.setattr(si, "_is_windows", lambda: False)
    ran = []

    def boom():
        raise RuntimeError("release failed")

    inh = si.SleepInhibitor()
    inh._releases = [("a", lambda: ran.append("a")),
                     ("b", boom),
                     ("c", lambda: ran.append("c"))]
    inh.release()  # must not raise
    assert ran == ["a", "c"]
    assert inh.is_active() is False


def test_linux_orchestration_portal_wins(monkeypatch):
    monkeypatch.setattr(si, "_is_windows", lambda: False)
    order = []
    monkeypatch.setattr(si.SleepInhibitor, "_acquire_portal",
                        lambda self: order.append("portal") or True)
    monkeypatch.setattr(si.SleepInhibitor, "_acquire_screensaver",
                        lambda self: order.append("ss") or True)
    monkeypatch.setattr(si.SleepInhibitor, "_acquire_login1",
                        lambda self: order.append("l1") or True)
    inh = si.SleepInhibitor()
    inh._releases.append(("portal", lambda: None))  # portal records a thunk
    tier = inh.acquire()
    assert tier == "portal"
    assert order == ["portal"]  # fallback never attempted


def test_linux_orchestration_falls_back_when_portal_fails(monkeypatch):
    monkeypatch.setattr(si, "_is_windows", lambda: False)
    monkeypatch.setattr(si.SleepInhibitor, "_acquire_portal", lambda self: False)
    monkeypatch.setattr(si.SleepInhibitor, "_acquire_screensaver", lambda self: True)
    monkeypatch.setattr(si.SleepInhibitor, "_acquire_login1", lambda self: True)
    inh = si.SleepInhibitor()
    tier = inh.acquire()
    assert tier == "screensaver+login1"


def test_linux_orchestration_returns_none_when_nothing_works(monkeypatch):
    monkeypatch.setattr(si, "_is_windows", lambda: False)
    monkeypatch.setattr(si.SleepInhibitor, "_acquire_portal", lambda self: False)
    monkeypatch.setattr(si.SleepInhibitor, "_acquire_screensaver", lambda self: False)
    monkeypatch.setattr(si.SleepInhibitor, "_acquire_login1", lambda self: False)
    inh = si.SleepInhibitor()
    assert inh.acquire() is None
    assert inh.is_active() is False


def test_portal_acquire_holds_and_closes(monkeypatch, rec):
    monkeypatch.setattr(si, "_is_windows", lambda: False)
    monkeypatch.setattr(si, "_session_bus", lambda: FakeBus(rec))
    inh = si.SleepInhibitor()
    tier = inh.acquire()
    assert tier == "portal"
    # Inhibit was called on the portal interface with the suspend|idle flags.
    name, args, kwargs = rec["inhibit"][0]
    assert name == "org.freedesktop.portal.Desktop"
    assert kwargs["dbus_interface"] == "org.freedesktop.portal.Inhibit"
    assert int(args[1]) == si.PORTAL_SUSPEND_IDLE
    assert args[2] == {"reason": si.REASON}
    # Release closes the returned request handle.
    inh.release()
    assert rec["close"][0][0] == "org.freedesktop.portal.Desktop"
    assert rec["close"][0][1] == "/portal/request/1"
    assert inh.is_active() is False


def test_portal_failure_returns_false(monkeypatch, rec):
    monkeypatch.setattr(si, "_is_windows", lambda: False)
    # Portal, ScreenSaver, and login1 all unreachable -> overall None.
    monkeypatch.setattr(
        si, "_session_bus",
        lambda: FakeBus(rec, fail_names={
            "org.freedesktop.portal.Desktop",
            "org.freedesktop.ScreenSaver",
        }),
    )
    monkeypatch.setattr(
        si, "_system_bus",
        lambda: FakeBus(rec, fail_names={"org.freedesktop.login1"}),
    )
    inh = si.SleepInhibitor()
    assert inh.acquire() is None


def test_fallback_acquires_screensaver_and_login1(monkeypatch, rec):
    monkeypatch.setattr(si, "_is_windows", lambda: False)
    # Portal unreachable -> fallback. ScreenSaver on session bus, login1 on system bus.
    monkeypatch.setattr(
        si, "_session_bus",
        lambda: FakeBus(rec, fail_names={"org.freedesktop.portal.Desktop"}),
    )
    monkeypatch.setattr(si, "_system_bus", lambda: FakeBus(rec))
    closed = []
    monkeypatch.setattr(si, "_close_fd", lambda fd: closed.append(fd))

    inh = si.SleepInhibitor()
    tier = inh.acquire()
    assert tier == "screensaver+login1"

    ss = [c for c in rec["inhibit"] if c[0] == "org.freedesktop.ScreenSaver"][0]
    assert ss[1] == (si.APP_NAME, si.REASON)
    assert ss[2]["dbus_interface"] == "org.freedesktop.ScreenSaver"
    l1 = [c for c in rec["inhibit"] if c[0] == "org.freedesktop.login1"][0]
    assert l1[1] == ("sleep:idle", si.APP_NAME, si.REASON, "block")

    inh.release()
    # ScreenSaver released via UnInhibit(cookie); login1 fd closed.
    assert rec["uninhibit"][0][1] == (42,)
    assert closed == [7]
    assert inh.is_active() is False


def test_fallback_screensaver_only_when_login1_unreachable(monkeypatch, rec):
    monkeypatch.setattr(si, "_is_windows", lambda: False)
    monkeypatch.setattr(
        si, "_session_bus",
        lambda: FakeBus(rec, fail_names={"org.freedesktop.portal.Desktop"}),
    )
    # System bus unreachable (the Flatpak sandbox case).
    monkeypatch.setattr(
        si, "_system_bus",
        lambda: FakeBus(rec, fail_names={"org.freedesktop.login1"}),
    )
    inh = si.SleepInhibitor()
    assert inh.acquire() == "screensaver"
