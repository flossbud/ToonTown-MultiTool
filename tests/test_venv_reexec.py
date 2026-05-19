"""utils.venv_reexec decision logic: when to re-exec main.py through
the project's venv interpreter and when to leave the current process
alone.

Tests run inside a venv (the project's ./venv), so sys.prefix !=
sys.base_prefix by default. Every test that expects re-exec must
monkeypatch sys.prefix back to sys.base_prefix to simulate "system
Python, not in any venv".
"""

import os
import sys
from unittest.mock import patch

from utils.venv_reexec import reexec_into_venv


def _make_fake_venv(tmp_path):
    """Create a fake ./venv/bin/python (or Scripts/python.exe) at
    tmp_path, return its absolute path."""
    if sys.platform == "win32":
        venv_python = tmp_path / "venv" / "Scripts" / "python.exe"
    else:
        venv_python = tmp_path / "venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("#!/bin/sh\nexit 0\n")
    venv_python.chmod(0o755)
    return venv_python


def _simulate_system_python(monkeypatch):
    """Make sys.prefix == sys.base_prefix to simulate running under
    system Python (no venv active)."""
    monkeypatch.setattr(sys, "prefix", sys.base_prefix)


def test_skips_when_opt_out_env_var_set(monkeypatch, tmp_path):
    monkeypatch.setenv("TTMT_NO_VENV_REEXEC", "1")
    _make_fake_venv(tmp_path)
    _simulate_system_python(monkeypatch)
    script = tmp_path / "main.py"
    script.write_text("")
    with patch("os.execv") as execv:
        reexec_into_venv(str(script))
    execv.assert_not_called()


def test_skips_when_frozen(monkeypatch, tmp_path):
    monkeypatch.delenv("TTMT_NO_VENV_REEXEC", raising=False)
    _make_fake_venv(tmp_path)
    _simulate_system_python(monkeypatch)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    script = tmp_path / "main.py"
    script.write_text("")
    with patch("os.execv") as execv:
        reexec_into_venv(str(script))
    execv.assert_not_called()


def test_skips_when_venv_missing(monkeypatch, tmp_path):
    """User cloned the repo but never ran install.sh; ./venv doesn't
    exist. Re-exec must silently no-op so the user sees the eventual
    PySide6 ImportError (or system-Python crash, if installed) with
    a clear actionable trail rather than a re-exec OSError."""
    monkeypatch.delenv("TTMT_NO_VENV_REEXEC", raising=False)
    _simulate_system_python(monkeypatch)
    # tmp_path has no ./venv subdir at all
    script = tmp_path / "main.py"
    script.write_text("")
    with patch("os.execv") as execv:
        reexec_into_venv(str(script))
    execv.assert_not_called()


def test_skips_when_in_project_venv(monkeypatch, tmp_path):
    """We're already running under the project's own ./venv/bin/python
    (this is the second pass after a successful re-exec). Must skip
    to avoid an infinite re-exec loop."""
    monkeypatch.delenv("TTMT_NO_VENV_REEXEC", raising=False)
    venv_python = _make_fake_venv(tmp_path)
    # Real venv interpreters set sys.prefix to the venv root and
    # sys.base_prefix to the original Python install. Make them differ
    # to simulate "we're in a venv".
    monkeypatch.setattr(sys, "prefix", str(tmp_path / "venv"))
    monkeypatch.setattr(sys, "base_prefix", "/usr")
    script = tmp_path / "main.py"
    script.write_text("")
    with patch("os.execv") as execv:
        reexec_into_venv(str(script))
    execv.assert_not_called()
    # silence "unused" lint on venv_python
    assert venv_python.exists()


def test_skips_when_in_user_other_venv(monkeypatch, tmp_path):
    """User activated their OWN venv (e.g. for testing a different
    PySide6 version) and ran `python main.py`. Don't redirect them
    into ./venv -- they explicitly chose their setup."""
    monkeypatch.delenv("TTMT_NO_VENV_REEXEC", raising=False)
    _make_fake_venv(tmp_path)
    # User's venv is somewhere unrelated; sys.prefix points there,
    # sys.base_prefix is the system Python.
    monkeypatch.setattr(sys, "prefix", "/home/user/.my-test-venv")
    monkeypatch.setattr(sys, "base_prefix", "/usr")
    script = tmp_path / "main.py"
    script.write_text("")
    with patch("os.execv") as execv:
        reexec_into_venv(str(script))
    execv.assert_not_called()


def test_execs_into_venv_when_conditions_met(monkeypatch, tmp_path):
    """Happy path: system Python, working venv, no opt-out -> re-exec."""
    monkeypatch.delenv("TTMT_NO_VENV_REEXEC", raising=False)
    venv_python = _make_fake_venv(tmp_path)
    _simulate_system_python(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["main.py", "--self-check"])
    script = tmp_path / "main.py"
    script.write_text("")
    with patch("os.execv") as execv:
        reexec_into_venv(str(script))
    execv.assert_called_once()
    args, _kwargs = execv.call_args
    # First arg: the executable to invoke
    assert args[0] == str(venv_python)
    # Second arg: the argv list. argv[0] should be the venv python,
    # argv[1] the script path (absolute), argv[2+] the original script args.
    assert args[1] == [
        str(venv_python),
        str(script.resolve()),
        "--self-check",
    ]


def test_passes_script_args_through(monkeypatch, tmp_path):
    """Multiple script args (including ones that look like flags) are
    forwarded verbatim."""
    monkeypatch.delenv("TTMT_NO_VENV_REEXEC", raising=False)
    venv_python = _make_fake_venv(tmp_path)
    _simulate_system_python(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["main.py", "--foo", "bar", "--baz=qux"])
    script = tmp_path / "main.py"
    script.write_text("")
    with patch("os.execv") as execv:
        reexec_into_venv(str(script))
    args, _ = execv.call_args
    assert args[1][2:] == ["--foo", "bar", "--baz=qux"]
    # silence "unused" lint
    assert venv_python.exists()
