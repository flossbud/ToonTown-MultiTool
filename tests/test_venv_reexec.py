"""utils.venv_reexec decision logic: when to spawn the venv interpreter,
when to retry on fatal-signal exits, and when to leave the current
process alone.

Tests run inside a venv (the project's ./venv), so sys.prefix !=
sys.base_prefix by default. Every test that expects spawn must
monkeypatch sys.prefix back to sys.base_prefix to simulate "system
Python, not in any venv".
"""

import signal
import sys
from unittest.mock import MagicMock, patch

import pytest

from utils.venv_reexec import (
    MAX_LAUNCH_ATTEMPTS,
    _supervise_with_retry,
    reexec_into_venv,
)


def _make_fake_venv(tmp_path):
    """Create a fake ./venv/bin/python (or Scripts/python.exe), return path."""
    if sys.platform == "win32":
        venv_python = tmp_path / "venv" / "Scripts" / "python.exe"
    else:
        venv_python = tmp_path / "venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("#!/bin/sh\nexit 0\n")
    venv_python.chmod(0o755)
    return venv_python


def _simulate_system_python(monkeypatch):
    """Make sys.prefix == sys.base_prefix to simulate system Python."""
    monkeypatch.setattr(sys, "prefix", sys.base_prefix)


# ============================================================
# Skip-condition tests (reexec_into_venv exits early)
# ============================================================


def test_skips_when_opt_out_env_var_set(monkeypatch, tmp_path):
    monkeypatch.setenv("TTMT_NO_VENV_REEXEC", "1")
    _make_fake_venv(tmp_path)
    _simulate_system_python(monkeypatch)
    script = tmp_path / "main.py"
    script.write_text("")
    with patch("subprocess.Popen") as popen:
        reexec_into_venv(str(script))
    popen.assert_not_called()


def test_skips_when_frozen(monkeypatch, tmp_path):
    monkeypatch.delenv("TTMT_NO_VENV_REEXEC", raising=False)
    _make_fake_venv(tmp_path)
    _simulate_system_python(monkeypatch)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    script = tmp_path / "main.py"
    script.write_text("")
    with patch("subprocess.Popen") as popen:
        reexec_into_venv(str(script))
    popen.assert_not_called()


def test_skips_when_venv_missing(monkeypatch, tmp_path):
    """User cloned the repo but never ran install.sh; ./venv doesn't exist."""
    monkeypatch.delenv("TTMT_NO_VENV_REEXEC", raising=False)
    _simulate_system_python(monkeypatch)
    script = tmp_path / "main.py"
    script.write_text("")
    with patch("subprocess.Popen") as popen:
        reexec_into_venv(str(script))
    popen.assert_not_called()


def test_skips_when_in_project_venv(monkeypatch, tmp_path):
    """Second pass after a successful supervisor spawn. Must skip
    to avoid recursion."""
    monkeypatch.delenv("TTMT_NO_VENV_REEXEC", raising=False)
    _make_fake_venv(tmp_path)
    monkeypatch.setattr(sys, "prefix", str(tmp_path / "venv"))
    monkeypatch.setattr(sys, "base_prefix", "/usr")
    script = tmp_path / "main.py"
    script.write_text("")
    with patch("subprocess.Popen") as popen:
        reexec_into_venv(str(script))
    popen.assert_not_called()


def test_skips_when_in_user_other_venv(monkeypatch, tmp_path):
    """User activated their own venv (different from ./venv); trust them."""
    monkeypatch.delenv("TTMT_NO_VENV_REEXEC", raising=False)
    _make_fake_venv(tmp_path)
    monkeypatch.setattr(sys, "prefix", "/home/user/.my-test-venv")
    monkeypatch.setattr(sys, "base_prefix", "/usr")
    script = tmp_path / "main.py"
    script.write_text("")
    with patch("subprocess.Popen") as popen:
        reexec_into_venv(str(script))
    popen.assert_not_called()


def test_spawns_venv_when_conditions_met(monkeypatch, tmp_path):
    """Happy path: system Python + working venv -> Popen the venv python."""
    monkeypatch.delenv("TTMT_NO_VENV_REEXEC", raising=False)
    venv_python = _make_fake_venv(tmp_path)
    _simulate_system_python(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["main.py", "--self-check"])
    script = tmp_path / "main.py"
    script.write_text("")

    fake_proc = MagicMock()
    fake_proc.wait.return_value = 0
    with patch("subprocess.Popen", return_value=fake_proc) as popen, \
         patch("sys.exit") as exit_mock:
        reexec_into_venv(str(script))

    popen.assert_called_once()
    cmd = popen.call_args[0][0]
    assert cmd[0] == str(venv_python)
    assert cmd[1] == str(script.resolve())
    assert cmd[2] == "--self-check"
    exit_mock.assert_called_once_with(0)


# ============================================================
# Retry-logic tests (_supervise_with_retry directly)
# ============================================================


class FakePopen:
    """Configurable subprocess.Popen stand-in for the retry tests."""

    def __init__(self, returncodes, durations):
        """returncodes[i] and durations[i] describe the i-th spawn."""
        self._returncodes = list(returncodes)
        self._durations = list(durations)
        self.call_log = []

    def __call__(self, cmd, *args, **kwargs):
        # Pop the next scripted (rc, duration) pair.
        idx = len(self.call_log)
        rc = self._returncodes[idx]
        dur = self._durations[idx]
        proc = MagicMock()
        proc.wait.return_value = rc
        # Patch time.monotonic so the supervisor sees `dur` seconds elapsed
        # between the spawn and the wait return.
        self.call_log.append((cmd, rc, dur))
        return proc


def _run_supervisor_with_scripted_runs(monkeypatch, returncodes, durations):
    """Run _supervise_with_retry with mocked Popen + time.monotonic so the
    perceived elapsed-since-spawn is `durations[i]` for the i-th spawn."""
    fake = FakePopen(returncodes, durations)
    # time.monotonic alternates: start-of-spawn-i, end-of-wait-i, start-of-spawn-(i+1), ...
    fake_times = []
    t = 100.0
    for d in durations:
        fake_times.append(t)         # start
        fake_times.append(t + d)     # after wait
        t += d + 0.001
    times_iter = iter(fake_times)
    monkeypatch.setattr("utils.venv_reexec.time.monotonic",
                        lambda: next(times_iter))
    monkeypatch.setattr("subprocess.Popen", fake)
    rc = _supervise_with_retry("/fake/venv/python", "/fake/main.py", [])
    return rc, fake.call_log


def test_retry_on_early_sigsegv(monkeypatch, capsys):
    """SIGSEGV at startup triggers a retry. If the retry succeeds,
    supervisor returns 0."""
    rc, log = _run_supervisor_with_scripted_runs(
        monkeypatch,
        returncodes=[-signal.SIGSEGV, 0],
        durations=[1.0, 5.0],
    )
    assert rc == 0
    assert len(log) == 2
    err = capsys.readouterr().err
    assert "Fatal-signal exit" in err
    assert "SIGSEGV" in err


def test_retry_on_early_sigbus(monkeypatch, capsys):
    """Same as above but for SIGBUS (the other observed crash signal)."""
    rc, log = _run_supervisor_with_scripted_runs(
        monkeypatch,
        returncodes=[-signal.SIGBUS, 0],
        durations=[0.5, 5.0],
    )
    assert rc == 0
    assert len(log) == 2
    assert "SIGBUS" in capsys.readouterr().err


def test_retry_on_late_sigsegv(monkeypatch, capsys):
    """A fatal signal long after startup (e.g. paint-time GC race on
    Python 3.14) also triggers a retry. The 3-second early-window
    distinction was removed; retries are bounded by MAX_LAUNCH_ATTEMPTS
    only."""
    rc, log = _run_supervisor_with_scripted_runs(
        monkeypatch,
        returncodes=[-signal.SIGSEGV, 0],
        durations=[600.0, 5.0],
    )
    assert rc == 0
    assert len(log) == 2
    err = capsys.readouterr().err
    assert "Fatal-signal exit" in err
    assert "SIGSEGV" in err


def test_no_retry_on_clean_nonzero_exit(monkeypatch):
    """Non-signal nonzero exit (e.g. main.py called sys.exit(1)) doesn't
    retry -- the program exited deliberately."""
    rc, log = _run_supervisor_with_scripted_runs(
        monkeypatch,
        returncodes=[1],
        durations=[0.5],
    )
    assert rc == 1
    assert len(log) == 1


def test_gives_up_after_max_attempts(monkeypatch, capsys):
    """If every attempt crashes with a fatal signal, supervisor returns
    the last failing returncode after MAX_LAUNCH_ATTEMPTS tries."""
    rc, log = _run_supervisor_with_scripted_runs(
        monkeypatch,
        returncodes=[-signal.SIGSEGV] * MAX_LAUNCH_ATTEMPTS,
        durations=[0.5] * MAX_LAUNCH_ATTEMPTS,
    )
    assert rc == -signal.SIGSEGV
    assert len(log) == MAX_LAUNCH_ATTEMPTS
    # Should have logged MAX_LAUNCH_ATTEMPTS - 1 retries
    err = capsys.readouterr().err
    assert err.count("Fatal-signal exit") == MAX_LAUNCH_ATTEMPTS - 1


def test_clean_zero_exit_returns_immediately(monkeypatch):
    """First spawn returns 0 -> supervisor returns 0, no retry."""
    rc, log = _run_supervisor_with_scripted_runs(
        monkeypatch,
        returncodes=[0],
        durations=[5.0],
    )
    assert rc == 0
    assert len(log) == 1
