"""Unit tests for services.sleep_inhibitor.SleepInhibitor.

All OS access (the systemd-inhibit holder/list subprocess, the QtDBus seams,
Win32 kernel32, fd close) is reached through module-level seams that these
tests monkeypatch, so no real subprocess, bus, or Win32 call is ever made.
"""

import subprocess
from types import SimpleNamespace

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
def test_windows_acquire_sets_system_and_display_flags(monkeypatch):
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


def test_holder_spawn_failure_degrades_to_fallback_without_raising(monkeypatch):
    """If the holder spawn raises (no systemd-inhibit/cat, sandbox denial),
    acquire() must not propagate; it degrades to the fallback chain."""
    monkeypatch.setattr(si, "_is_windows", lambda: False)
    monkeypatch.setattr(si, "_uuid_token", lambda: "T")

    def boom(token):
        raise FileNotFoundError("systemd-inhibit")

    monkeypatch.setattr(si, "_popen_holder", boom)
    monkeypatch.setattr(si.SleepInhibitor, "_acquire_login1_qtdbus", lambda self: None)
    monkeypatch.setattr(si.SleepInhibitor, "_acquire_screensaver_qtdbus", lambda self: None)

    inh = si.SleepInhibitor()
    assert inh.acquire() is None          # no exception, no false success
    assert inh.is_active() is False
    assert inh.status.sleep_blocked is False


def test_reap_kills_holder_when_first_wait_times_out(monkeypatch):
    """_reap escalates to kill() when the holder does not exit on the first
    bounded wait -- the leak scenario the reap exists to handle."""
    events = []

    class StuckProc:
        def __init__(self):
            self._waits = 0

        def wait(self, timeout=None):
            self._waits += 1
            if self._waits == 1:
                raise subprocess.TimeoutExpired(cmd="cat", timeout=timeout)
            events.append("reaped")
            return -9

        def kill(self):
            events.append("killed")

    si._reap(StuckProc())
    assert events == ["killed", "reaped"]


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
