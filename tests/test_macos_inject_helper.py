"""Subprocess smoke tests for the self-contained injection helper.

macOS-only. Spawns scripts/macos_inject_helper.py under /usr/bin/python3 -s
(the Apple CLT python, which IS a platform binary on this host) with a scrubbed
environment, then drives it over JSON-line RPC. Covers the `hello` handshake
self-test and the reply / fire-and-forget channel invariant.
"""
import json
import os
import pathlib
import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin", reason="injection helper is macOS-only")

_HELPER = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "macos_inject_helper.py"
# The /usr/bin/python3 shim resolves to the active Command Line Tools python,
# which is an Apple platform binary (CS_PLATFORM_BINARY=True) on this host.
_CLT_PYTHON = "/usr/bin/python3"


def _run_helper(requests):
    """Spawn the helper under the scrubbed CLT python, pipe one JSON line per request,
    and return (stdout_reply_lines, stderr). Skips cleanly if the CLT python is absent."""
    assert _HELPER.exists(), f"helper not found at {_HELPER}"
    if not os.path.exists(_CLT_PYTHON):
        pytest.skip(f"CLT python not present at {_CLT_PYTHON}")
    # Scrubbed env (env -i style): only a minimal PATH, no venv / PyObjC leakage,
    # so this exercises the helper exactly as the shipped platform-binary child runs.
    proc = subprocess.Popen(
        [_CLT_PYTHON, "-s", str(_HELPER)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env={"PATH": "/usr/bin:/bin"}, text=True, bufsize=1,
    )
    payload = "".join(json.dumps(r) + "\n" for r in requests)
    try:
        out, err = proc.communicate(input=payload, timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        pytest.fail(f"helper timed out; stderr=\n{err}")
    finally:
        if proc.poll() is None:
            proc.terminate()
    return [ln for ln in out.splitlines() if ln.strip()], err


def test_hello_handshake_selftest():
    lines, err = _run_helper([{"op": "hello", "id": 7}])
    assert lines, f"no reply on stdout; stderr=\n{err}"
    reply = json.loads(lines[0])  # stdout is JSON-only; first line is the reply
    assert reply.get("ok") is True, reply
    assert reply.get("id") == 7, reply
    assert reply.get("protocol") == 1, reply
    assert reply.get("platform_binary") is True, reply
    assert reply.get("skylight_ok") is True, reply
    assert reply.get("objc_ok") is True, reply


def test_post_ops_are_fire_and_forget_and_keep_channel_in_sync():
    """A failing fire-and-forget post op (it raises in arg-parse before the engine,
    missing pid/wid) must NOT emit a stdout line; the following ping reply must be the
    FIRST and ONLY line. This locks the channel invariant (a stray line would be
    misread as the ping reply and desync the parent)."""
    lines, err = _run_helper([{"op": "press"}, {"op": "ping", "id": 3}])
    assert len(lines) == 1, f"expected exactly one reply line, got {lines}; stderr=\n{err}"
    reply = json.loads(lines[0])
    assert reply.get("ok") is True, reply
    assert reply.get("id") == 3, reply
    assert "available" in reply, reply
