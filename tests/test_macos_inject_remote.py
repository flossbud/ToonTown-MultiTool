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
    "helper-crashed",
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

# The pure correlation-id read tests (platform-independent) live in
# tests/test_macos_inject_remote_rpc.py so they run on ALL CI, not just macOS.


def _bare(rem):
    """A _RemoteDelivery whose __init__ (and thus spawn) is bypassed, with just the
    attributes _handshake touches initialised. Lets us drive the handshake matrix by
    stubbing _rpc, no real helper."""
    d = rem._RemoteDelivery.__new__(rem._RemoteDelivery)
    d._available = False
    d._reason = None
    return d


def test_handshake_success_sets_available(monkeypatch):
    """A reply with platform_binary + objc_ok + skylight_ok all True -> available, no reason."""
    import utils.macos_inject_remote as rem

    d = _bare(rem)
    monkeypatch.setattr(d, "_rpc", lambda op, **k: {
        "ok": True, "platform_binary": True, "objc_ok": True, "skylight_ok": True})
    assert d._handshake() is True
    assert d.available is True
    assert d.last_reason() is None


@pytest.mark.parametrize("reply,expected", [
    (None, "helper-timeout"),                                    # no reply / timeout
    ({"ok": True}, "helper-not-platform-binary"),                # platform_binary absent
    ({"platform_binary": True}, "objc-init-failed"),             # objc_ok absent
    ({"platform_binary": True, "objc_ok": True}, "skylight-symbol-missing"),  # skylight_ok absent
])
def test_handshake_reason_matrix(monkeypatch, reply, expected):
    """Each handshake field maps to its distinct latched reason, in spec order."""
    import utils.macos_inject_remote as rem

    d = _bare(rem)
    monkeypatch.setattr(d, "_rpc", lambda op, **k: reply)
    assert d._handshake() is False
    assert d.available is False
    assert d.last_reason() == expected


def test_spawn_env_is_scrubbed(monkeypatch):
    """The child env must be EXACTLY {"PATH": "/usr/bin:/bin"} (no DYLD_*/PYTHON*/venv
    leakage) and argv must pass -s. Capture the Popen kwargs, then abort the spawn."""
    import utils.macos_inject_remote as rem

    captured = {}

    def fake_popen(argv, **kwargs):
        captured["argv"] = argv
        captured["env"] = kwargs.get("env")
        raise OSError("captured; abort spawn before a real child starts")

    monkeypatch.setattr(rem.macos_clt, "clt_state", lambda: (True, None, "/fake/clt/python3"))
    monkeypatch.setattr(rem, "_helper_path", lambda: "/fake/ttmt_inject/macos_inject_helper.py")
    monkeypatch.setattr(rem.subprocess, "Popen", fake_popen)

    d = rem._RemoteDelivery()
    try:
        assert captured["argv"] == [
            "/fake/clt/python3", "-s", "/fake/ttmt_inject/macos_inject_helper.py"]
        env = captured["env"]
        assert env == {"PATH": "/usr/bin:/bin"}
        assert not any(k.startswith("DYLD_") or k.startswith("PYTHON") for k in env)
        # Popen raised -> spawn failed -> latched reason, not-available.
        assert d.available is False
        assert d.last_reason() == "helper-spawn-failed"
    finally:
        d.shutdown()
