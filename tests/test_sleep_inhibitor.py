"""Unit tests for services.sleep_inhibitor.SleepInhibitor.

All OS access (D-Bus session/system buses, Win32 kernel32, fd close) is
reached through module-level seams that these tests monkeypatch, so no real
bus or Win32 call is ever made.
"""

import os
from types import SimpleNamespace

import pytest

import services.sleep_inhibitor as si


class FakeHolder:
    """Stand-in for the systemd-inhibit Popen handle."""
    def __init__(self):
        self.terminated = False
        self.waited = False
        self.returncode = 0
    def poll(self):
        return None if not self.terminated else 0
    def wait(self, timeout=None):
        self.waited = True
        return 0


def test_systemd_layer_acquires_and_verifies(monkeypatch):
    monkeypatch.setattr(si, "_is_windows", lambda: False)
    monkeypatch.setattr(si, "_uuid_token", lambda: "TOKENXYZ")
    spawned = {}
    def fake_popen_holder(token):
        spawned["token"] = token
        spawned["write_fd_open"] = True
        return FakeHolder(), 99  # (proc, write_fd)
    monkeypatch.setattr(si, "_popen_holder", fake_popen_holder)
    # --list returns a row containing our token
    monkeypatch.setattr(si, "_run_list",
                        lambda: "ToonTown MultiTool 1000 jaret 1 systemd-inhibit "
                                "sleep:idle Keep-Alive is active [TOKENXYZ] block\n")
    monkeypatch.setattr(si, "_close_write_fd", lambda fd: spawned.update(write_fd_open=False))
    # Layer 2 + fallback off for this test
    monkeypatch.setattr(si.SleepInhibitor, "_acquire_login1_qtdbus", lambda self: None)
    monkeypatch.setattr(si.SleepInhibitor, "_acquire_screensaver_qtdbus", lambda self: None)

    inh = si.SleepInhibitor()
    tier = inh.acquire()
    assert tier == "systemd"
    assert inh.is_active() is True
    assert inh.status.sleep_blocked is True
    assert inh.status.method == "systemd"
    assert spawned["token"] == "TOKENXYZ"


def test_systemd_layer_unverified_cleans_up_then_returns_none(monkeypatch):
    monkeypatch.setattr(si, "_is_windows", lambda: False)
    monkeypatch.setattr(si, "_uuid_token", lambda: "TOKENXYZ")
    holder = FakeHolder()
    closed = {"write": False, "reaped": False}
    monkeypatch.setattr(si, "_popen_holder", lambda token: (holder, 99))
    monkeypatch.setattr(si, "_run_list", lambda: "no token here\n")  # never verifies
    monkeypatch.setattr(si, "_close_write_fd", lambda fd: closed.update(write=True))
    monkeypatch.setattr(si, "_reap", lambda proc: closed.update(reaped=True))
    monkeypatch.setattr(si.SleepInhibitor, "_acquire_login1_qtdbus", lambda self: None)
    monkeypatch.setattr(si.SleepInhibitor, "_acquire_screensaver_qtdbus", lambda self: None)

    inh = si.SleepInhibitor()
    tier = inh.acquire()
    assert tier is None
    assert inh.is_active() is False
    assert inh.status.sleep_blocked is False
    assert closed["write"] is True and closed["reaped"] is True


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


def test_reacquire_releases_before_acquiring(monkeypatch):
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
    assert inh.acquire() == "windows"  # re-acquire releases first, never stacks
    # acquire (set flags), release (ES_CONTINUOUS), acquire again (set flags).
    set_flags = 0x80000000 | 0x00000001 | 0x00000002
    assert calls == [set_flags, 0x80000000, set_flags]


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


def test_tab_delegates_acquire_and_release(monkeypatch):
    """The tab's inhibitor methods delegate to SleepInhibitor and log the
    tier. Built via __new__ to avoid the heavy MultitoonTab.__init__ (Qt,
    InputService, etc.)."""
    from tabs.multitoon._tab import MultitoonTab

    tab = MultitoonTab.__new__(MultitoonTab)
    logs = []
    tab.log = lambda m: logs.append(m)
    state = {"active": False}
    tab._sleep_inhibitor = SimpleNamespace(
        acquire=lambda: state.update(active=True) or "portal",
        is_active=lambda: state["active"],
        release=lambda: state.update(active=False),
    )

    MultitoonTab._acquire_sleep_inhibitor(tab)
    assert any("portal" in m for m in logs)

    MultitoonTab._release_sleep_inhibitor(tab)
    assert any("released" in m.lower() for m in logs)


def test_tab_logs_warning_when_acquire_fails(monkeypatch):
    from tabs.multitoon._tab import MultitoonTab

    tab = MultitoonTab.__new__(MultitoonTab)
    logs = []
    tab.log = lambda m: logs.append(m)
    tab._sleep_inhibitor = SimpleNamespace(
        acquire=lambda: None,
        is_active=lambda: False,
        release=lambda: None,
    )
    MultitoonTab._acquire_sleep_inhibitor(tab)
    assert any("could not" in m.lower() for m in logs)
