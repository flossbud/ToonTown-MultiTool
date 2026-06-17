"""THROWAWAY prototype (gated by TTMT_MACOS_INJECT_HELPER): route the production
MacOSMouseDelivery interface to a platform-binary /usr/bin/python3 helper process
(scripts/macos_inject_helper.py) via synchronous JSON-line RPC.

Tests whether a platform-binary child (spawned BY the failing non-platform GUI
app) can actuate SLEventPostToPid where the in-process non-platform engine can't.
NO in-process fallback by design: a helper failure must surface as not-available,
so a pass/fail is unambiguous.
"""
from __future__ import annotations

import json
import os
import select
import subprocess
import sys
import threading

_SYSTEM_PYTHON = "/usr/bin/python3"   # Apple CLT, CS_PLATFORM_BINARY=True
_RPC_TIMEOUT_S = 5.0


class _RemoteDelivery:
    """Mirrors the MacOSMouseDelivery surface the backend uses (available,
    resolve_psn, resolve_owner, press, release, motion) over RPC to the helper."""

    def __init__(self):
        self._lock = threading.Lock()
        self._proc = None
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self._logf = open(os.path.expanduser("~/ttmt_inject_helper.log"), "a")
        try:
            self._proc = subprocess.Popen(
                [_SYSTEM_PYTHON, os.path.join("scripts", "macos_inject_helper.py")],
                cwd=repo_root, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=self._logf, text=True, bufsize=1,
            )
            print(f"[inject-remote] spawned platform-binary helper "
                  f"{_SYSTEM_PYTHON} pid={self._proc.pid} (log ~/ttmt_inject_helper.log)",
                  file=sys.stderr, flush=True)
        except Exception as e:
            print(f"[inject-remote] FAILED to spawn helper: {e}", file=sys.stderr, flush=True)
            self._proc = None

    def _rpc(self, req):
        proc = self._proc
        if proc is None or proc.poll() is not None:
            return None
        with self._lock:
            try:
                proc.stdin.write(json.dumps(req) + "\n")
                proc.stdin.flush()
                ready, _, _ = select.select([proc.stdout], [], [], _RPC_TIMEOUT_S)
                if not ready:
                    print("[inject-remote] RPC timeout", file=sys.stderr, flush=True)
                    return None
                line = proc.stdout.readline()
                return json.loads(line) if line else None
            except Exception as e:
                print(f"[inject-remote] RPC error: {e}", file=sys.stderr, flush=True)
                return None

    @property
    def available(self):
        r = self._rpc({"op": "ping"})
        return bool(r and r.get("available"))

    def resolve_psn(self, wid):
        r = self._rpc({"op": "resolve_psn", "wid": int(wid)})
        if not (r and r.get("ok")):
            return None
        h = r.get("psn") or ""
        return bytes.fromhex(h) if h else None

    def resolve_owner(self, wid):
        r = self._rpc({"op": "resolve_owner", "wid": int(wid)})
        return (r or {}).get("owner")

    def _req(self, op, pid, wid, psn, win_xy, screen_xy, dragging=False):
        req = {
            "op": op, "pid": int(pid), "wid": int(wid),
            "psn": psn.hex() if psn else "",
            "win": [float(win_xy[0]), float(win_xy[1])],
            "screen": [float(screen_xy[0]), float(screen_xy[1])],
        }
        if op == "motion":
            req["dragging"] = bool(dragging)
        return req

    def _send_noreply(self, req) -> bool:
        """Fire-and-forget write (no round-trip) for the high-frequency hover/drag
        stream, so the dispatch thread never blocks on a per-motion reply."""
        proc = self._proc
        if proc is None or proc.poll() is not None:
            return False
        with self._lock:
            try:
                proc.stdin.write(json.dumps(req) + "\n")
                proc.stdin.flush()
                return True
            except Exception as e:
                print(f"[inject-remote] send error: {e}", file=sys.stderr, flush=True)
                return False

    # All post ops are fire-and-forget (no round-trip). press()/release() return
    # True optimistically (assumed-success): the backend then stores/clears the
    # gesture binding as usual. Tradeoff (review-flagged): a genuinely-failed post
    # is invisible; a dropped release at worst leaves a stray 'up' (harmless).
    def press(self, pid, wid, psn, win_xy, screen_xy):
        return self._send_noreply(self._req("press", pid, wid, psn, win_xy, screen_xy))

    def release(self, pid, wid, psn, win_xy, screen_xy):
        return self._send_noreply(self._req("release", pid, wid, psn, win_xy, screen_xy))

    def motion(self, pid, wid, psn, win_xy, screen_xy, dragging):
        return self._send_noreply(self._req("motion", pid, wid, psn, win_xy, screen_xy, dragging))
