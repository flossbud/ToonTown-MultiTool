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
