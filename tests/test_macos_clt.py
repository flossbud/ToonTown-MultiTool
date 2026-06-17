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
