"""Tests for MacOSBackend._engine() self-selecting in-process vs helper by
whether THIS process is an Apple platform binary (macOS only)."""
import sys

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin", reason="macOS-only engine gate"
)


class _InProc:
    def __init__(self, **k):
        self.kwargs = k


class _Remote:
    def __init__(self, **k):
        self.kwargs = k


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
    eng = b._engine()
    assert isinstance(eng, _InProc)
    assert "ledger" in eng.kwargs   # in-process engine MUST receive the echo ledger
    monkeypatch.setattr(macos_platform_binary, "is_platform_binary", lambda: False)
    b._delivery = None
    eng = b._engine()
    assert isinstance(eng, _Remote)
    assert eng.kwargs == {}         # helper proxy ctor takes NO args (yet)


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


def test_disable_send_paths_degrade_to_false(monkeypatch):
    """With the engine disabled, the public send paths must return False, NOT raise
    AttributeError on a None engine (even when a window otherwise resolves)."""
    from utils import macos_backend, macos_platform_binary

    _patch_engines(monkeypatch)
    monkeypatch.setattr(macos_platform_binary, "is_platform_binary", lambda: True)
    monkeypatch.setenv("TTMT_MACOS_INJECT", "disable")
    b = macos_backend.MacOSBackend()
    b._delivery = None
    monkeypatch.setattr(b, "_resolve_pid", lambda w: 4321)  # a window would resolve
    assert b._resolve_target("123") is None                 # guarded, no AttributeError
    assert b.send_button_press("123", 1, 2, 3, 4) is False
    assert b.send_motion("123", 1, 2, 3, 4) is False
