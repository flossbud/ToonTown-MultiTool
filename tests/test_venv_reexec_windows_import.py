"""Regression test: utils.venv_reexec must import on Windows where
signal.SIGBUS is absent.

CI history: a prior change to `_RETRYABLE_FATAL_SIGNALS` referenced
`signal.SIGBUS` unconditionally, which raised AttributeError at module
load time on win32 and broke `python main.py --self-check` in the
test-windows CI job.
"""

import importlib
import signal
import sys


def test_module_imports_when_sigbus_absent(monkeypatch):
    """Simulate the Windows interpreter (no signal.SIGBUS) and confirm
    venv_reexec still imports cleanly."""
    # Delete SIGBUS from the signal module for the duration of the test.
    monkeypatch.delattr(signal, "SIGBUS", raising=False)
    # Force a fresh import so module-level code re-runs without SIGBUS.
    sys.modules.pop("utils.venv_reexec", None)
    importlib.import_module("utils.venv_reexec")  # must not raise


def test_retryable_set_contains_only_ints_and_filters_missing(monkeypatch):
    monkeypatch.delattr(signal, "SIGBUS", raising=False)
    sys.modules.pop("utils.venv_reexec", None)
    venv_reexec = importlib.import_module("utils.venv_reexec")
    # SIGSEGV and SIGABRT still exist; SIGBUS got filtered out.
    expected = {-signal.SIGSEGV, -signal.SIGABRT}
    assert venv_reexec._RETRYABLE_FATAL_SIGNALS == expected


def test_retryable_set_has_all_three_on_linux():
    """Sanity check that the normal Linux path still includes all three
    signals so the retry behavior is unchanged."""
    if not hasattr(signal, "SIGBUS"):
        # Real Windows; skip rather than fail.
        return
    sys.modules.pop("utils.venv_reexec", None)
    venv_reexec = importlib.import_module("utils.venv_reexec")
    expected = {-signal.SIGSEGV, -signal.SIGBUS, -signal.SIGABRT}
    assert venv_reexec._RETRYABLE_FATAL_SIGNALS == expected
