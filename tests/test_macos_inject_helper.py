"""Subprocess smoke test for the self-contained injection helper.

macOS-only. Spawns scripts/macos_inject_helper.py under /usr/bin/python3 -s
(the Apple CLT python, which IS a platform binary on this host) with a scrubbed
environment, performs the `hello` handshake over JSON-line RPC, and asserts the
self-test reports a working platform-binary + SkyLight + ObjC bridge.
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


def test_hello_handshake_selftest():
    assert _HELPER.exists(), f"helper not found at {_HELPER}"
    # Scrubbed env (env -i style): only a minimal PATH, no venv / PyObjC leakage,
    # so this exercises the helper exactly as the shipped platform-binary child runs.
    proc = subprocess.Popen(
        [_CLT_PYTHON, "-s", str(_HELPER)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env={"PATH": "/usr/bin:/bin"}, text=True, bufsize=1,
    )
    try:
        out, err = proc.communicate(input=json.dumps({"op": "hello", "id": 7}) + "\n", timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        pytest.fail(f"helper timed out; stderr=\n{err}")
    finally:
        if proc.poll() is None:
            proc.terminate()

    # The first non-empty stdout line is the JSON reply (stdout is JSON-only).
    line = next((ln for ln in out.splitlines() if ln.strip()), "")
    assert line, f"no reply on stdout; stderr=\n{err}"
    reply = json.loads(line)

    assert reply.get("ok") is True, reply
    assert reply.get("id") == 7, reply
    assert reply.get("protocol") == 1, reply
    assert reply.get("platform_binary") is True, reply
    assert reply.get("skylight_ok") is True, reply
    assert reply.get("objc_ok") is True, reply
