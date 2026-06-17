"""Tests for the CS_PLATFORM_BINARY self-detection helper (macOS only)."""
import sys

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin", reason="macOS-only (csops/CS_PLATFORM_BINARY)"
)


def test_decode_and_self():
    from utils import macos_platform_binary as p

    assert p.decode(0x04000000) is True
    assert p.decode(0x00000000) is False
    assert p.is_platform_binary() in (True, False)  # never raises
    assert p.is_platform_binary() == p.is_platform_binary()  # cached/stable


def test_fail_safe_to_false_on_probe_error(monkeypatch):
    """A csops probe error must fail safe to False (-> use the helper), never raise."""
    from utils import macos_platform_binary as p

    def _boom():
        raise OSError("csops failed")

    monkeypatch.setattr(p, "_cached", None)  # clear the per-process cache for this test
    monkeypatch.setattr(p, "csflags", _boom)
    assert p.is_platform_binary() is False


def test_is_platform_binary_probes_csflags_once(monkeypatch):
    """The once-per-process contract: csflags() is invoked at most once, not per call."""
    from utils import macos_platform_binary as p

    calls = {"n": 0}

    def _counting():
        calls["n"] += 1
        return 0x04000000

    monkeypatch.setattr(p, "_cached", None)  # restored by monkeypatch after the test
    monkeypatch.setattr(p, "csflags", _counting)
    assert p.is_platform_binary() is True
    assert p.is_platform_binary() is True
    assert calls["n"] == 1  # cached after the first probe
