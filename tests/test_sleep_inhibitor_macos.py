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
