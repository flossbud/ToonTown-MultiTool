"""macOS (darwin) branch of services.sleep_inhibitor.SleepInhibitor.

All OS access (caffeinate holder, pmset) is reached through module seams these
tests monkeypatch, so no real caffeinate/pmset runs. sys.platform / _is_macos
are pinned where relevant (project_platform_branch_breaks_unpinned_tests)."""

import os
import subprocess

import pytest

import services.sleep_inhibitor as si


# A pmset -g assertions fixture: our holder is cat pid 4242, owned by caffeinate
# pid 5001 with all three assertion types. Traps: a stray caffeinate (pid 9999,
# timeout-based, no '(pid 4242)') and coreaudiod's 'Created for PID: 4242.'
# (uppercase 'PID:', no parens) must NOT match.
PMSET_ALL_THREE = """\
Assertion status system-wide:
   PreventUserIdleSystemSleep     1
Listed by owning process:
   pid 5001(caffeinate): [0x0001] 00:00:01 PreventUserIdleSystemSleep named: "caffeinate command-line tool"
\tDetails: caffeinate asserting on behalf of 'cat' (pid 4242)
\tLocalized=THE CAFFEINATE TOOL IS PREVENTING SLEEP.
   pid 5001(caffeinate): [0x0002] 00:00:01 PreventUserIdleDisplaySleep named: "caffeinate command-line tool"
\tDetails: caffeinate asserting on behalf of 'cat' (pid 4242)
   pid 5001(caffeinate): [0x0003] 00:00:01 PreventSystemSleep named: "caffeinate command-line tool"
\tDetails: caffeinate asserting on behalf of 'cat' (pid 4242)
   pid 9999(caffeinate): [0x0004] 00:03:00 PreventUserIdleSystemSleep named: "caffeinate command-line tool"
\tDetails: caffeinate asserting for 300 secs
   pid 597(coreaudiod): [0x0005] 00:12:00 PreventUserIdleSystemSleep named: "com.apple.audio"
\tCreated for PID: 4242.
"""

PMSET_ONLY_TWO = """\
Listed by owning process:
   pid 5001(caffeinate): [0x0001] 00:00:01 PreventUserIdleSystemSleep named: "caffeinate command-line tool"
\tDetails: caffeinate asserting on behalf of 'cat' (pid 4242)
   pid 5001(caffeinate): [0x0002] 00:00:01 PreventUserIdleDisplaySleep named: "caffeinate command-line tool"
\tDetails: caffeinate asserting on behalf of 'cat' (pid 4242)
"""


def test_types_for_pid_finds_all_three_and_ignores_traps():
    types = si._caffeinate_types_for_pid(PMSET_ALL_THREE, 4242)
    assert types == {
        "PreventUserIdleSystemSleep",
        "PreventUserIdleDisplaySleep",
        "PreventSystemSleep",
    }


def test_types_for_pid_partial_returns_subset():
    types = si._caffeinate_types_for_pid(PMSET_ONLY_TWO, 4242)
    assert types == {"PreventUserIdleSystemSleep", "PreventUserIdleDisplaySleep"}


def test_types_for_pid_absent_returns_empty():
    assert si._caffeinate_types_for_pid(PMSET_ALL_THREE, 1234) == set()
    assert si._caffeinate_types_for_pid("", 4242) == set()


def test_run_pmset_assertions_returns_stdout_on_clean_exit(monkeypatch):
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(argv, 0, stdout="OUT", stderr="")

    monkeypatch.setattr(si.subprocess, "run", fake_run)
    out = si._run_pmset_assertions(timeout=0.5)
    assert out == "OUT"
    assert captured["argv"] == ["/usr/bin/pmset", "-g", "assertions"]
    assert captured["kwargs"]["timeout"] == 0.5
    assert captured["kwargs"]["env"]["LC_ALL"] == "C"


def test_run_pmset_assertions_empty_on_nonzero_exit(monkeypatch):
    monkeypatch.setattr(si.subprocess, "run",
                        lambda argv, **k: subprocess.CompletedProcess(argv, 1, stdout="JUNK", stderr=""))
    assert si._run_pmset_assertions(timeout=0.5) == ""


def test_run_pmset_assertions_empty_on_exception(monkeypatch):
    def boom(argv, **k):
        raise subprocess.TimeoutExpired(argv, 0.5)
    monkeypatch.setattr(si.subprocess, "run", boom)
    assert si._run_pmset_assertions(timeout=0.5) == ""


def test_popen_caffeinate_builds_argv_and_wires_pipe_stdin(monkeypatch):
    captured = {}

    class FakeProc:
        pid = 4242

    def fake_popen(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return FakeProc()

    monkeypatch.setattr(si.subprocess, "Popen", fake_popen)

    proc, w_fd = si._popen_caffeinate()
    try:
        assert captured["argv"] == ["/usr/bin/caffeinate", "-dis", "--", "/bin/cat"]
        kw = captured["kwargs"]
        assert isinstance(kw["stdin"], int)        # pipe read end as stdin
        assert kw["stdin"] in kw["pass_fds"]
        assert isinstance(w_fd, int)
        assert proc.pid == 4242
    finally:
        si._close_write_fd(w_fd)


def test_popen_caffeinate_closes_both_fds_on_spawn_failure(monkeypatch):
    made = {}
    real_pipe = os.pipe

    def fake_pipe():
        r, w = real_pipe()
        made["r"], made["w"] = r, w
        return r, w

    monkeypatch.setattr(os, "pipe", fake_pipe)
    monkeypatch.setattr(si.subprocess, "Popen",
                        lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("caffeinate")))

    with pytest.raises(FileNotFoundError):
        si._popen_caffeinate()

    for fd in (made["r"], made["w"]):
        with pytest.raises(OSError):
            os.fstat(fd)   # closed -> EBADF


class FakeCaffeinate:
    """Stand-in for the caffeinate -- cat Popen handle. pid is the cat pid."""
    def __init__(self, pid=4242, alive=True):
        self.pid = pid
        self._alive = alive
        self.waited = False
    def poll(self):
        return None if self._alive else 0
    def wait(self, timeout=None):
        self.waited = True
        return 0


def test_verify_caffeinate_true_when_all_three_present(monkeypatch):
    monkeypatch.setattr(si, "_run_pmset_assertions", lambda timeout=None: PMSET_ALL_THREE)
    inh = si.SleepInhibitor()
    assert inh._verify_caffeinate(FakeCaffeinate(pid=4242)) is True


def test_verify_caffeinate_false_on_partial_coverage(monkeypatch):
    # Only two of the three types reference our pid -> not verified.
    monkeypatch.setattr(si, "_run_pmset_assertions", lambda timeout=None: PMSET_ONLY_TWO)
    monkeypatch.setattr(si, "_VERIFY_DEADLINE", 0.2)  # don't poll the full 1.5s
    inh = si.SleepInhibitor()
    assert inh._verify_caffeinate(FakeCaffeinate(pid=4242)) is False


def test_verify_caffeinate_false_when_holder_exited(monkeypatch):
    # A dead holder holds nothing; verify must short-circuit without trusting pmset.
    called = {"pmset": False}
    def fake_pmset(timeout=None):
        called["pmset"] = True
        return PMSET_ALL_THREE
    monkeypatch.setattr(si, "_run_pmset_assertions", fake_pmset)
    inh = si.SleepInhibitor()
    assert inh._verify_caffeinate(FakeCaffeinate(pid=4242, alive=False)) is False
    assert called["pmset"] is False   # liveness checked BEFORE polling pmset


def _patch_macos_success(monkeypatch, holder):
    """Pin darwin, stub a successful caffeinate spawn + verification. Returns a
    recorder dict: closed_fds (write-fds closed) and reaped (procs reaped)."""
    monkeypatch.setattr(si, "_is_macos", lambda: True)
    monkeypatch.setattr(si, "_is_windows", lambda: False)
    monkeypatch.setattr(si, "_run_pmset_assertions", lambda timeout=None: PMSET_ALL_THREE)
    rec = {"closed_fds": [], "reaped": []}
    monkeypatch.setattr(si, "_popen_caffeinate", lambda: (holder, 99))
    monkeypatch.setattr(si, "_close_write_fd", lambda fd: rec["closed_fds"].append(fd))
    monkeypatch.setattr(si, "_reap", lambda proc: rec["reaped"].append(proc))
    return rec


def test_acquire_macos_success_sets_status_and_release(monkeypatch):
    holder = FakeCaffeinate(pid=4242)
    rec = _patch_macos_success(monkeypatch, holder)

    inh = si.SleepInhibitor()
    tier = inh.acquire()                       # dispatch -> _acquire_macos
    assert tier == "caffeinate"
    assert inh.active_tier == "caffeinate"
    assert inh.is_active() is True
    assert inh.status.sleep_blocked is True
    assert inh.status.screen_lock_cookie_held is True
    assert inh.status.method == "caffeinate"
    assert rec["reaped"] == []                 # nothing released yet

    inh.release()                              # EOF + reap the holder
    assert 99 in rec["closed_fds"]
    assert holder in rec["reaped"]
    assert inh.is_active() is False
    assert inh.status.sleep_blocked is False


def test_acquire_macos_unverified_cleans_up_and_returns_none(monkeypatch):
    holder = FakeCaffeinate(pid=4242)
    monkeypatch.setattr(si, "_is_macos", lambda: True)
    monkeypatch.setattr(si, "_is_windows", lambda: False)
    monkeypatch.setattr(si, "_VERIFY_DEADLINE", 0.2)
    monkeypatch.setattr(si, "_run_pmset_assertions", lambda timeout=None: "no match\n")
    closed = {"write": False, "reaped": False}
    monkeypatch.setattr(si, "_popen_caffeinate", lambda: (holder, 99))
    monkeypatch.setattr(si, "_close_write_fd", lambda fd: closed.update(write=True))
    monkeypatch.setattr(si, "_reap", lambda proc: closed.update(reaped=True))

    inh = si.SleepInhibitor()
    assert inh.acquire() is None
    assert inh.status.sleep_blocked is False
    assert closed["write"] is True and closed["reaped"] is True   # holder not leaked


def test_acquire_macos_spawn_failure_returns_none(monkeypatch):
    monkeypatch.setattr(si, "_is_macos", lambda: True)
    monkeypatch.setattr(si, "_is_windows", lambda: False)
    monkeypatch.setattr(si, "_popen_caffeinate",
                        lambda: (_ for _ in ()).throw(FileNotFoundError("caffeinate")))
    inh = si.SleepInhibitor()
    assert inh.acquire() is None
    assert inh.status.sleep_blocked is False


def test_acquire_macos_verifier_exception_cleans_up(monkeypatch):
    holder = FakeCaffeinate(pid=4242)
    monkeypatch.setattr(si, "_is_macos", lambda: True)
    monkeypatch.setattr(si, "_is_windows", lambda: False)
    closed = {"write": False, "reaped": False}
    monkeypatch.setattr(si, "_popen_caffeinate", lambda: (holder, 99))
    monkeypatch.setattr(si, "_close_write_fd", lambda fd: closed.update(write=True))
    monkeypatch.setattr(si, "_reap", lambda proc: closed.update(reaped=True))
    monkeypatch.setattr(si.SleepInhibitor, "_verify_caffeinate",
                        lambda self, proc: (_ for _ in ()).throw(RuntimeError("boom")))
    inh = si.SleepInhibitor()
    assert inh.acquire() is None                 # exception did not propagate
    assert closed["write"] is True and closed["reaped"] is True   # cleaned up


def test_acquire_macos_reacquire_releases_first(monkeypatch):
    holder1 = FakeCaffeinate(pid=4242)
    rec = _patch_macos_success(monkeypatch, holder1)
    inh = si.SleepInhibitor()
    assert inh.acquire() == "caffeinate"
    # Second acquire: release-before-acquire must reap the first holder. holder2
    # reuses pid 4242 so the pinned PMSET_ALL_THREE fixture still verifies it.
    holder2 = FakeCaffeinate(pid=4242)
    monkeypatch.setattr(si, "_popen_caffeinate", lambda: (holder2, 77))
    assert inh.acquire() == "caffeinate"
    assert holder1 in rec["reaped"]             # first holder released on re-acquire


def test_release_macos_idempotent_and_never_raises(monkeypatch):
    monkeypatch.setattr(si, "_is_macos", lambda: True)
    inh = si.SleepInhibitor()
    # release with nothing held is a safe no-op
    inh.release()
    assert inh.is_active() is False
