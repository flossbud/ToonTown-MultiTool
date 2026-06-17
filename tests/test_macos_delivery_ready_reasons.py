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
