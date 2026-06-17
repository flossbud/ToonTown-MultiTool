"""Tests for MacOSBackend._engine() self-selecting in-process vs helper by
whether THIS process is an Apple platform binary (macOS only)."""
import sys

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin", reason="macOS-only engine gate"
)


class _InProc:
    def __init__(self, **k):
        pass


class _Remote:
    def __init__(self, **k):
        pass


def _patch_engines(monkeypatch):
    import utils.macos_mouse_delivery as mmd
    import utils.macos_inject_remote as rem

    monkeypatch.setattr(mmd, "MacOSMouseDelivery", _InProc)
    monkeypatch.setattr(rem, "_RemoteDelivery", _Remote)


def test_engine_gate_selects_by_platform_binary(monkeypatch):
    from utils import macos_backend, macos_platform_binary

    _patch_engines(monkeypatch)
    b = macos_backend.MacOSBackend()
    monkeypatch.setattr(macos_platform_binary, "is_platform_binary", lambda: True)
    b._delivery = None
    assert isinstance(b._engine(), _InProc)
    monkeypatch.setattr(macos_platform_binary, "is_platform_binary", lambda: False)
    b._delivery = None
    assert isinstance(b._engine(), _Remote)


def test_engine_gate_dev_override(monkeypatch):
    from utils import macos_backend, macos_platform_binary

    _patch_engines(monkeypatch)
    monkeypatch.setattr(macos_platform_binary, "is_platform_binary", lambda: True)
    monkeypatch.setenv("TTMT_MACOS_INJECT", "force-helper")
    b = macos_backend.MacOSBackend()
    b._delivery = None
    assert isinstance(b._engine(), _Remote)


def test_engine_gate_force_inprocess_overrides_non_platform(monkeypatch):
    """force-inprocess pins the in-process engine even on a non-platform binary."""
    from utils import macos_backend, macos_platform_binary

    _patch_engines(monkeypatch)
    monkeypatch.setattr(macos_platform_binary, "is_platform_binary", lambda: False)
    monkeypatch.setenv("TTMT_MACOS_INJECT", "force-inprocess")
    b = macos_backend.MacOSBackend()
    b._delivery = None
    assert isinstance(b._engine(), _InProc)


def test_engine_gate_disable_returns_none(monkeypatch):
    """disable yields no engine; readiness then fail-closes upstream."""
    from utils import macos_backend, macos_platform_binary

    _patch_engines(monkeypatch)
    monkeypatch.setattr(macos_platform_binary, "is_platform_binary", lambda: True)
    monkeypatch.setenv("TTMT_MACOS_INJECT", "disable")
    b = macos_backend.MacOSBackend()
    b._delivery = None
    assert b._engine() is None
