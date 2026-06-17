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
