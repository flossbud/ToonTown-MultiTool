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
