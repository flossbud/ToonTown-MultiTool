"""mouse_delivery_ready() returns DISTINCT, actionable reasons so the UI can guide
the user: CLT-missing (helper path only) vs accessibility-denied vs a specific
helper/SkyLight fault. All seams (platform-binary, CLT, post-access, engine) are
monkeypatched so the assertions hold regardless of the host's real CLT/codesign state.
"""
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS delivery readiness")

from utils import macos_clt, macos_platform_binary
from utils.macos_backend import MacOSBackend


class _StubEngine:
    """Mirrors the bit of the delivery surface mouse_delivery_ready() reads."""
    def __init__(self, available=True, reason=None):
        self._available = available
        self._reason = reason

    @property
    def available(self):
        return self._available

    def last_reason(self):
        return self._reason


def test_clt_missing_on_helper_path_returns_clt_reason(monkeypatch):
    # Non-platform-binary process -> helper path -> CLT is required.
    monkeypatch.setattr(macos_platform_binary, "is_platform_binary", lambda: False)
    monkeypatch.setattr(
        macos_clt, "clt_state",
        lambda: (False, "Mouse click sync needs Xcode Command Line Tools", None),
    )
    b = MacOSBackend()
    # has_post_access / _engine must NOT be reached; if they were, surface it loudly.
    monkeypatch.setattr(b, "has_post_access", lambda: pytest.fail("CLT gate should short-circuit"))
    ready, reason = b.mouse_delivery_ready()
    assert ready is False
    assert "Command Line Tools" in reason


def test_accessibility_denied_returns_access_reason(monkeypatch):
    # Platform binary -> CLT gate skipped; denied post-access -> the access reason.
    monkeypatch.setattr(macos_platform_binary, "is_platform_binary", lambda: True)
    monkeypatch.setattr(macos_clt, "clt_state", lambda: pytest.fail("CLT must be skipped"))
    b = MacOSBackend()
    monkeypatch.setattr(b, "has_post_access", lambda: False)
    ready, reason = b.mouse_delivery_ready()
    assert ready is False
    assert "accessibility" in reason.lower()


def test_engine_unavailable_surfaces_helper_last_reason(monkeypatch):
    # A _RemoteDelivery-style engine latches a specific fault; it must flow through verbatim.
    monkeypatch.setattr(macos_platform_binary, "is_platform_binary", lambda: True)
    b = MacOSBackend()
    monkeypatch.setattr(b, "has_post_access", lambda: True)
    monkeypatch.setattr(b, "_engine", lambda: _StubEngine(available=False, reason="helper-crashed"))
    ready, reason = b.mouse_delivery_ready()
    assert ready is False
    assert reason == "helper-crashed"


def test_helper_tcc_denied_maps_to_readable_accessibility_reason(monkeypatch):
    """The helper lacking its OWN post-event access (tcc-denied) - even when the app has
    access - surfaces the SAME readable, actionable wording as the app-side denial, not the
    raw token, so the tooltip/dialog guides 'grant Accessibility'."""
    monkeypatch.setattr(macos_platform_binary, "is_platform_binary", lambda: True)
    b = MacOSBackend()
    monkeypatch.setattr(b, "has_post_access", lambda: True)   # the APP has access
    monkeypatch.setattr(b, "_engine", lambda: _StubEngine(available=False, reason="tcc-denied"))
    ready, reason = b.mouse_delivery_ready()
    assert ready is False
    assert "accessibility" in reason.lower()
    assert reason != "tcc-denied"   # mapped to readable prose, not the raw token


def test_engine_none_returns_disabled_reason(monkeypatch):
    # The TTMT_MACOS_INJECT=disable dev override -> _engine() is None: a clean reason, no AttributeError.
    monkeypatch.setattr(macos_platform_binary, "is_platform_binary", lambda: True)
    b = MacOSBackend()
    monkeypatch.setattr(b, "has_post_access", lambda: True)
    monkeypatch.setattr(b, "_engine", lambda: None)
    ready, reason = b.mouse_delivery_ready()
    assert ready is False
    assert reason == "mouse delivery disabled"


def test_ready_path_returns_true_none(monkeypatch):
    monkeypatch.setattr(macos_platform_binary, "is_platform_binary", lambda: True)
    b = MacOSBackend()
    monkeypatch.setattr(b, "has_post_access", lambda: True)
    monkeypatch.setattr(b, "_engine", lambda: _StubEngine(available=True))
    assert b.mouse_delivery_ready() == (True, None)


def test_inprocess_engine_without_last_reason_gets_generic_message(monkeypatch):
    """The in-process engine has NO last_reason(); the callable-guard must fall back to the
    generic SkyLight message rather than crash on a missing attribute."""
    monkeypatch.setattr(macos_platform_binary, "is_platform_binary", lambda: True)

    class _NoReasonEngine:
        available = False   # unavailable, and deliberately NO last_reason method

    b = MacOSBackend()
    monkeypatch.setattr(b, "has_post_access", lambda: True)
    monkeypatch.setattr(b, "_engine", lambda: _NoReasonEngine())
    ready, reason = b.mouse_delivery_ready()
    assert ready is False
    assert "SkyLight" in reason or "unavailable" in reason


def test_clt_state_cache_probes_once_per_ttl(monkeypatch):
    """_clt_state(): the None sentinel forces a first-call probe; the result is reused within
    _CLT_TTL; a reprobe happens after the TTL (so a guided CLT install is picked up). This
    avoids a per-recompute xcode-select fork while staying fresh within seconds."""
    import utils.macos_backend as mb

    clock = {"t": 100.0}
    monkeypatch.setattr(mb.time, "monotonic", lambda: clock["t"])
    calls = {"n": 0}

    def counting():
        calls["n"] += 1
        return (calls["n"] == 1, None, "/py")   # first probe True, later reprobe False

    monkeypatch.setattr(macos_clt, "clt_state", counting)
    b = MacOSBackend()

    assert b._clt_state() == (True, None, "/py")   # first call probes (None sentinel)
    assert calls["n"] == 1
    clock["t"] += 1.0                              # within TTL -> cached, no reprobe
    assert b._clt_state() == (True, None, "/py")
    assert calls["n"] == 1
    clock["t"] += mb._CLT_TTL + 1                  # past TTL -> reprobe
    assert b._clt_state() == (False, None, "/py")
    assert calls["n"] == 2


def test_force_inprocess_skips_clt_gate(monkeypatch):
    """Dev override force-inprocess uses the in-process engine, so readiness must NOT gate on
    CLT even on a non-platform-binary process (the predicate must match _engine())."""
    monkeypatch.setattr(macos_platform_binary, "is_platform_binary", lambda: False)
    monkeypatch.setenv("TTMT_MACOS_INJECT", "force-inprocess")
    monkeypatch.setattr(macos_clt, "clt_state", lambda: pytest.fail("CLT must be skipped for in-process"))
    b = MacOSBackend()
    monkeypatch.setattr(b, "has_post_access", lambda: True)
    monkeypatch.setattr(b, "_engine", lambda: _StubEngine(available=True))
    assert b.mouse_delivery_ready() == (True, None)
