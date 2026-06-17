"""Tests for utils.macos_clt: CLT detection that never executes /usr/bin/python3."""

import sys

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin", reason="CLT detection is macOS-only"
)


def test_clt_state_shape(monkeypatch):
    from utils import macos_clt

    # developer dir selected + python present -> available
    monkeypatch.setattr(
        macos_clt, "_xcode_select_p", lambda: "/Library/Developer/CommandLineTools"
    )
    monkeypatch.setattr(macos_clt, "_path_executable", lambda p: True)
    ok, reason, py = macos_clt.clt_state()
    assert ok is True and reason is None and py.endswith("/usr/bin/python3")

    # no developer dir -> not available, with a reason, NEVER runs python3
    monkeypatch.setattr(macos_clt, "_xcode_select_p", lambda: None)
    ok, reason, py = macos_clt.clt_state()
    assert ok is False and "Command Line Tools" in reason


def test_clt_state_devdir_set_but_no_python(monkeypatch):
    """Second guard: dev dir active but no usable python3 anywhere -> not available."""
    from utils import macos_clt

    monkeypatch.setattr(
        macos_clt,
        "_xcode_select_p",
        lambda: "/Applications/Xcode.app/Contents/Developer",
    )
    monkeypatch.setattr(macos_clt, "_path_executable", lambda p: False)
    ok, reason, py = macos_clt.clt_state()
    assert ok is False and py is None and "Command Line Tools" in reason


def test_clt_state_falls_back_to_canonical_clt_when_xcode_active(monkeypatch):
    """Issue-1 regression: active dir is full Xcode whose bundle lacks python3, but
    standalone CLT is installed -> resolve the canonical CLT python (no dead-end)."""
    from utils import macos_clt

    monkeypatch.setattr(
        macos_clt,
        "_xcode_select_p",
        lambda: "/Applications/Xcode.app/Contents/Developer",
    )
    clt_py = macos_clt.CLT_DEFAULT_DIR + "/usr/bin/python3"
    monkeypatch.setattr(macos_clt, "_path_executable", lambda p: p == clt_py)
    ok, reason, py = macos_clt.clt_state()
    assert ok is True and reason is None and py == clt_py


def test_xcode_select_p_subprocess_contract(monkeypatch):
    """Verify the real subprocess contract: absolute xcode-select, no shell, a timeout,
    rc/stdout handling, and fail-closed on exception."""
    from utils import macos_clt

    class _R:
        def __init__(self, rc, out):
            self.returncode, self.stdout = rc, out

    calls = {}

    def ok_run(argv, **kw):
        calls["argv"], calls["kw"] = argv, kw
        return _R(0, "/Library/Developer/CommandLineTools\n")

    monkeypatch.setattr(macos_clt.subprocess, "run", ok_run)
    assert macos_clt._xcode_select_p() == "/Library/Developer/CommandLineTools"
    assert calls["argv"] == ["/usr/bin/xcode-select", "-p"]  # absolute path, list (no shell)
    assert calls["kw"].get("timeout") == 5
    assert calls["kw"].get("shell") is None                  # never shell=True

    monkeypatch.setattr(macos_clt.subprocess, "run", lambda *a, **k: _R(1, ""))
    assert macos_clt._xcode_select_p() is None               # nonzero rc -> None

    def boom(*a, **k):
        raise OSError("xcode-select missing")

    monkeypatch.setattr(macos_clt.subprocess, "run", boom)
    assert macos_clt._xcode_select_p() is None               # exception -> fail-closed


def test_open_clt_installer_invokes_xcode_select_install(monkeypatch):
    """User-initiated remediation: spawns `xcode-select --install` (the official GUI
    installer), absolute path, no shell, returns True; any failure -> False."""
    from utils import macos_clt

    calls = {}

    def fake_popen(argv, *a, **k):
        calls["argv"], calls["kw"] = argv, k
        return object()

    monkeypatch.setattr(macos_clt.subprocess, "Popen", fake_popen)
    assert macos_clt.open_clt_installer() is True
    assert calls["argv"] == ["/usr/bin/xcode-select", "--install"]  # absolute, list (no shell)
    assert calls["kw"].get("shell") is None                         # never shell=True

    def boom(*a, **k):
        raise OSError("xcode-select missing")

    monkeypatch.setattr(macos_clt.subprocess, "Popen", boom)
    assert macos_clt.open_clt_installer() is False                  # exception -> False
