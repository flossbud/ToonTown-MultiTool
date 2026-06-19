"""--self-check exit handling.

A successful FROZEN macOS build occasionally crashes during interpreter
finalization AFTER the oracle prints "self-check OK" and returns 0 (a rare,
CI-only Shiboken/PyObjC frozen-bundle teardown flake; 8/8 clean locally). The
oracle's result is already known at that point, so on that specific boundary we
os._exit(0) to bypass the crash-prone finalization. EVERY other path (source
runs, non-macOS packages, and ALL failures) keeps normal sys.exit so genuine
teardown regressions and load errors stay visible.
"""
import os

# Must be set BEFORE `import main` (it re-execs into ./venv on import otherwise).
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")

import pytest


class _Exited(Exception):
    """Sentinel: stand in for the real process-terminating exits so execution
    stops at the chosen exit call (exactly as os._exit/sys.exit would)."""


def _patch_exits(monkeypatch, main):
    rec = {"flushed": []}

    def _os_exit(c):
        rec["os_exit"] = c
        raise _Exited

    def _sys_exit(c=0):
        rec["sys_exit"] = c
        raise _Exited

    monkeypatch.setattr(main.os, "_exit", _os_exit)
    monkeypatch.setattr(main.sys, "exit", _sys_exit)
    monkeypatch.setattr(main.sys.stdout, "flush", lambda: rec["flushed"].append("out"))
    monkeypatch.setattr(main.sys.stderr, "flush", lambda: rec["flushed"].append("err"))
    return rec


def test_success_frozen_darwin_bypasses_finalization(monkeypatch):
    import main
    monkeypatch.setattr(main.sys, "platform", "darwin")
    monkeypatch.setattr(main.sys, "frozen", True, raising=False)
    rec = _patch_exits(monkeypatch, main)
    with pytest.raises(_Exited):
        main._self_check_exit(0)
    assert rec.get("os_exit") == 0       # the flaky boundary -> os._exit(0)
    assert "sys_exit" not in rec         # and never reaches sys.exit


def test_success_nonfrozen_darwin_uses_normal_exit(monkeypatch):
    # From-source macOS run: keep normal teardown (regressions stay visible).
    import main
    monkeypatch.setattr(main.sys, "platform", "darwin")
    monkeypatch.setattr(main.sys, "frozen", False, raising=False)
    rec = _patch_exits(monkeypatch, main)
    with pytest.raises(_Exited):
        main._self_check_exit(0)
    assert rec.get("sys_exit") == 0
    assert "os_exit" not in rec


def test_success_frozen_nondarwin_uses_normal_exit(monkeypatch):
    # Frozen Linux/Windows package: keep normal teardown.
    import main
    monkeypatch.setattr(main.sys, "platform", "linux")
    monkeypatch.setattr(main.sys, "frozen", True, raising=False)
    rec = _patch_exits(monkeypatch, main)
    with pytest.raises(_Exited):
        main._self_check_exit(0)
    assert rec.get("sys_exit") == 0
    assert "os_exit" not in rec


def test_failure_never_bypassed_even_on_frozen_darwin(monkeypatch):
    # A real load/build error must NEVER be masked.
    import main
    monkeypatch.setattr(main.sys, "platform", "darwin")
    monkeypatch.setattr(main.sys, "frozen", True, raising=False)
    rec = _patch_exits(monkeypatch, main)
    with pytest.raises(_Exited):
        main._self_check_exit(1)
    assert rec.get("sys_exit") == 1
    assert "os_exit" not in rec


def test_flushes_stdout_and_stderr_before_exit(monkeypatch):
    import main
    monkeypatch.setattr(main.sys, "platform", "darwin")
    monkeypatch.setattr(main.sys, "frozen", True, raising=False)
    rec = _patch_exits(monkeypatch, main)
    with pytest.raises(_Exited):
        main._self_check_exit(0)
    assert set(rec["flushed"]) == {"out", "err"}
