"""Unit tests for the parent-side _RemoteDelivery proxy (Task 4b).

macOS-only. Covers helper-path resolution order, the clt-missing / spawn-failed
not-available latches, and the correlation-id-validated RPC read (which discards a
stale/late reply from a prior timed-out request). The id-validation test drives an
injectable line-reader, so it needs NO real helper process.
"""
import sys

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin", reason="macOS-only injection remote proxy")

_DEFINED_REASONS = {
    "clt-missing", "helper-spawn-failed", "helper-not-platform-binary",
    "objc-init-failed", "skylight-symbol-missing", "helper-timeout",
}


def test_remote_unavailable_when_helper_path_missing(monkeypatch):
    """A nonexistent helper script (valid interpreter) spawns a child that dies before
    replying; the handshake then yields no reply. available is False with a defined
    reason."""
    import utils.macos_clt as clt
    import utils.macos_inject_remote as rem

    # Real CLT python (so Popen succeeds) but a helper path that does not exist.
    ok, _r, py = clt.clt_state()
    if not (ok and py):
        py = "/usr/bin/python3"
    monkeypatch.setattr(rem.macos_clt, "clt_state", lambda: (True, None, py))
    monkeypatch.setattr(rem, "_helper_path", lambda: "/nonexistent/ttmt/macos_inject_helper.py")

    d = rem._RemoteDelivery()
    try:
        assert d.available is False
        assert d.last_reason() in _DEFINED_REASONS
    finally:
        d.shutdown()


def test_helper_path_resolution(monkeypatch, tmp_path):
    """Resolution order: bundle Resources -> _MEIPASS -> repo. The first that actually
    contains ttmt_inject/macos_inject_helper.py wins."""
    import utils.macos_inject_remote as rem

    def _make_root(name):
        root = tmp_path / name
        (root / "ttmt_inject").mkdir(parents=True)
        (root / "ttmt_inject" / "macos_inject_helper.py").write_text("# stub\n")
        return str(root)

    bundle_root = _make_root("bundle")
    meipass_root = _make_root("meipass")

    # 1) bundle present -> bundle wins even if _MEIPASS is also present.
    monkeypatch.setattr(rem, "_bundle_resource_path", lambda: bundle_root)
    monkeypatch.setattr(rem, "_meipass_path", lambda: meipass_root)
    assert rem._helper_path() == str(tmp_path / "bundle" / "ttmt_inject" / "macos_inject_helper.py")

    # 2) no bundle -> _MEIPASS wins.
    monkeypatch.setattr(rem, "_bundle_resource_path", lambda: None)
    monkeypatch.setattr(rem, "_meipass_path", lambda: meipass_root)
    assert rem._helper_path() == str(tmp_path / "meipass" / "ttmt_inject" / "macos_inject_helper.py")

    # 3) neither bundle nor _MEIPASS -> repo scripts/ path (which exists in source).
    monkeypatch.setattr(rem, "_bundle_resource_path", lambda: None)
    monkeypatch.setattr(rem, "_meipass_path", lambda: None)
    assert rem._helper_path() == rem._repo_helper_path()


def test_clt_missing_latches_reason(monkeypatch):
    """clt_state not-ok -> no spawn, latched reason 'clt-missing'."""
    import utils.macos_inject_remote as rem

    spawned = {"called": False}

    def _boom(*a, **k):
        spawned["called"] = True
        raise AssertionError("must NOT spawn when CLT is missing")

    monkeypatch.setattr(
        rem.macos_clt, "clt_state",
        lambda: (False, "Mouse click sync needs Xcode Command Line Tools", None))
    monkeypatch.setattr(rem.subprocess, "Popen", _boom)

    d = rem._RemoteDelivery()
    try:
        assert spawned["called"] is False
        assert d.available is False
        assert d.last_reason() == "clt-missing"
    finally:
        d.shutdown()


def test_correlation_id_discards_stale_reply(monkeypatch):
    """The id-validation read must discard a stale/late reply (wrong id) and return the
    matching-id reply. Driven through an injectable line-reader, no real helper."""
    import json

    import utils.macos_inject_remote as rem

    # Build an instance WITHOUT spawning (bypass __init__'s spawn) so we can unit-test
    # the pure read logic in isolation.
    d = rem._RemoteDelivery.__new__(rem._RemoteDelivery)

    awaited = 42
    lines = [
        json.dumps({"ok": True, "id": 7, "stale": True}),   # late reply for a prior req
        json.dumps({"ok": True, "id": awaited, "psn": "ab"}),  # the one we want
    ]
    it = iter(lines)

    def fake_read_line(remaining):
        # remaining must stay positive across both reads (generous timeout below).
        assert remaining > 0
        return next(it, None)

    reply = d._recv_matching(awaited, fake_read_line, timeout=5.0)
    assert reply is not None
    assert reply.get("id") == awaited
    assert reply.get("psn") == "ab"


def test_correlation_id_timeout_when_only_stale(monkeypatch):
    """If only stale replies arrive then the reader signals EOF/timeout, the result is
    None (never a stale reply misreported as ours)."""
    import json

    import utils.macos_inject_remote as rem

    d = rem._RemoteDelivery.__new__(rem._RemoteDelivery)
    lines = [json.dumps({"ok": True, "id": 1}), None]  # stale, then EOF
    it = iter(lines)

    def fake_read_line(remaining):
        return next(it, None)

    assert d._recv_matching(99, fake_read_line, timeout=5.0) is None
