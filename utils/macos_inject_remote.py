"""Parent-side proxy that routes the production MacOSMouseDelivery interface to a
platform-binary helper child (scripts/macos_inject_helper.py) over synchronous
JSON-line RPC.

The private SkyLight SLEventPostToPid mouse path only actuates from an Apple
*platform binary* process. The shipped GUI app (a framework/PyInstaller python)
is NOT a platform binary, so it spawns the helper under the Xcode Command Line
Tools python (/Library/Developer/CommandLineTools/usr/bin/python3, a platform
binary) and forwards the delivery interface to it.

NO in-process fallback by design: a helper failure surfaces as not-available with
a single latched reason, so readiness upstream fail-closes unambiguously.

Task 4b scope: helper-path resolution, scrubbed-env spawn of the CLT python, a
validated `hello` handshake, and correlation-id-validated synchronous RPC (which
fixes a late-reply desync: a stale reply from a prior timed-out request can no
longer be misread as the next request's reply). Respawn-on-crash, the circuit
breaker, RPC-timeout->kill+respawn, and full no-zombie lifecycle are Task 4c.
"""
from __future__ import annotations

import json
import os
import select
import subprocess
import sys
import threading
import time

from utils import macos_clt

_RPC_TIMEOUT_S = 5.0

# Helper script location RELATIVE to a bundle/_MEIPASS resources root. The .app and
# the PyInstaller bundle both ship the helper (and macos_mouse_delivery.py) FLAT in
# a ttmt_inject/ subdirectory of the resources root.
_HELPER_REL = ("ttmt_inject", "macos_inject_helper.py")

# Scrubbed child environment: a minimal PATH ONLY. Dropping DYLD_*/PYTHON*/venv vars
# is what keeps the CLT python a clean platform binary (no injected libraries, no
# inherited site/venv that could shadow the flat-bundle engine import).
_SCRUBBED_ENV = {"PATH": "/usr/bin:/bin"}


def _bundle_resource_path() -> str | None:
    """The running .app bundle's Resources dir, or None. Lazy Foundation import so a
    non-Cocoa context (or a build without PyObjC) never raises; failures map to None."""
    try:
        from Foundation import NSBundle  # noqa: PLC0415  (lazy, optional at runtime)

        rp = NSBundle.mainBundle().resourcePath()
        return str(rp) if rp else None
    except Exception:
        return None


def _meipass_path() -> str | None:
    """PyInstaller onefile extraction dir, or None when not frozen."""
    return getattr(sys, "_MEIPASS", None)


def _repo_helper_path() -> str:
    """The helper script in the repo source layout (scripts/macos_inject_helper.py)."""
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "scripts", "macos_inject_helper.py",
    )


def _helper_path() -> str:
    """Resolve the platform-binary helper script. Resolution order:
      1. .app bundle Resources/ttmt_inject/macos_inject_helper.py
      2. PyInstaller _MEIPASS/ttmt_inject/macos_inject_helper.py
      3. repo scripts/macos_inject_helper.py (running from source)
    Returns the first that exists, else the repo path (so a missing-bundle case still
    has a concrete value to spawn/report). Never raises."""
    candidates: list[str] = []
    rp = _bundle_resource_path()
    if rp:
        candidates.append(os.path.join(rp, *_HELPER_REL))
    mp = _meipass_path()
    if mp:
        candidates.append(os.path.join(mp, *_HELPER_REL))
    repo = _repo_helper_path()
    candidates.append(repo)
    for c in candidates:
        try:
            if os.path.exists(c):
                return c
        except Exception:
            continue
    return repo


def _helper_log_path() -> str:
    """~/.cache/toontown-multitool/inject_helper.log (XDG_CACHE_HOME-aware), matching
    the faulthandler log convention. The helper's stderr (its own diagnostics) is
    captured here; the JSON-RPC reply channel is stdout and stays clean."""
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(base, "toontown-multitool", "inject_helper.log")


class _RemoteDelivery:
    """Mirrors the MacOSMouseDelivery surface the backend uses (available,
    resolve_psn, resolve_owner, press, release, motion) over RPC to the helper.

    `available` is True only once the helper has spawned AND a `hello` handshake has
    validated it as a platform binary with a working SkyLight + ObjC bridge.
    `last_reason()` returns the single latched fault token when not available."""

    def __init__(self, ledger=None):
        self._lock = threading.Lock()
        self._proc = None
        self._next_id = 1
        self._available = False
        self._reason: str | None = None
        # Accepted for signature parity with the in-process engine. The helper records
        # into its OWN ledger (it runs the engine), so it is intentionally unused here.
        self._ledger = ledger
        self._logf = None
        self._spawn_and_handshake()

    # ---- spawn + handshake ----------------------------------------------------

    def _spawn_and_handshake(self) -> None:
        ok, _reason, clt_python = macos_clt.clt_state()
        if not (ok and clt_python):
            # CLT absent: do NOT spawn (spawning /usr/bin/python3 with no developer dir
            # would pop the Xcode installer). Latch and stay unavailable.
            self._reason = "clt-missing"
            return
        helper = _helper_path()
        if not self._spawn(clt_python, helper):
            self._reason = "helper-spawn-failed"
            return
        if not self._handshake():
            # Spawned but unusable (wrong identity / objc / skylight / no reply). The
            # child is otherwise healthy and would block on stdin forever, so tear it
            # down NOW rather than leak a resident helper + pipes + logfile for the whole
            # session (this is the common unsupported-machine path). shutdown() preserves
            # the latched reason; the full respawn lifecycle is Task 4c.
            self.shutdown()

    def _spawn(self, clt_python: str, helper_path: str) -> bool:
        try:
            log_path = _helper_log_path()
            os.makedirs(os.path.dirname(log_path), exist_ok=True)  # don't depend on main.py import order
            self._logf = open(log_path, "a", buffering=1)
        except Exception:
            self._logf = subprocess.DEVNULL
        try:
            self._proc = subprocess.Popen(
                [clt_python, "-s", helper_path],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._logf,
                env=dict(_SCRUBBED_ENV), text=True, bufsize=1,
            )
            self._diag(f"spawned platform-binary helper {clt_python} -s {helper_path} "
                       f"pid={self._proc.pid}")
            return True
        except Exception as e:
            self._diag(f"FAILED to spawn helper {clt_python} -s {helper_path}: {e}")
            self._proc = None
            return False

    def _handshake(self) -> bool:
        """Validate the helper before marking available. Failure latches exactly one
        reason and leaves `available` False (checks ordered per the production spec).
        Returns True only when fully validated."""
        reply = self._rpc("hello")
        if reply is None:
            self._reason = "helper-timeout"
            return False
        if reply.get("platform_binary") is not True:
            self._reason = "helper-not-platform-binary"
            return False
        if reply.get("objc_ok") is not True:
            self._reason = "objc-init-failed"
            return False
        if reply.get("skylight_ok") is not True:
            self._reason = "skylight-symbol-missing"
            return False
        self._reason = None
        self._available = True
        self._diag("handshake validated; helper available")
        return True

    # ---- RPC ------------------------------------------------------------------

    def _make_reader(self, stdout):
        """A line-reader closure over the helper's stdout: read_line(remaining_s) ->
        the next reply line, or None on timeout / EOF (helper gone).

        Correctness rests on the helper being strictly request-driven: it writes a
        reply line ONLY in response to a replying-op and always emits a complete
        json+'\\n', so select+readline consumes exactly one whole line and stale vs
        fresh replies are time-separated. A future helper that volunteers stdout would
        break this single-line-per-read assumption."""
        def read_line(remaining: float):
            try:
                ready, _, _ = select.select([stdout], [], [], max(0.0, remaining))
            except Exception:
                return None
            if not ready:
                return None
            line = stdout.readline()
            return line if line else None
        return read_line

    def _recv_matching(self, awaited_id: int, read_line, timeout: float):
        """Read JSON-line replies via read_line(remaining_seconds) until one whose
        'id' == awaited_id arrives, or the timeout expires. A reply with a NON-matching
        id is a stale/late reply from a prior timed-out request: DISCARD it and keep
        reading. This is the correlation-id validation that prevents a late reply from
        being misread as this request's reply. Returns the matching dict or None.

        Structured to take an injectable line-reader so the id-validation logic is unit
        testable without a real helper process."""
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            line = read_line(remaining)
            if not line:
                return None  # timeout or EOF
            try:
                obj = json.loads(line)
            except Exception:
                continue  # unparseable: skip, keep reading
            if isinstance(obj, dict) and obj.get("id") == awaited_id:
                return obj
            # stale/late reply (or non-dict): discard and keep reading for our id

    def _rpc(self, op: str, **fields):
        """Synchronous request/reply carrying a unique correlation id. Returns the
        matching reply dict, or None on no-helper / write-error / timeout."""
        proc = self._proc
        if proc is None or proc.poll() is not None:
            return None
        with self._lock:
            req_id = self._next_id
            self._next_id += 1
            req = {"op": op, "id": req_id, **fields}
            try:
                proc.stdin.write(json.dumps(req) + "\n")
                proc.stdin.flush()
            except Exception as e:
                self._diag(f"RPC write error ({op}): {e}")
                return None
            return self._recv_matching(req_id, self._make_reader(proc.stdout), _RPC_TIMEOUT_S)

    # ---- public surface -------------------------------------------------------

    @property
    def available(self) -> bool:
        return self._available

    def last_reason(self) -> str | None:
        return self._reason

    def resolve_psn(self, wid):
        r = self._rpc("resolve_psn", wid=int(wid))
        if not (r and r.get("ok")):
            return None
        h = r.get("psn") or ""
        return bytes.fromhex(h) if h else None

    def resolve_owner(self, wid):
        r = self._rpc("resolve_owner", wid=int(wid))
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
        """Fire-and-forget write (no id, no round-trip) for the high-frequency
        hover/drag stream, so the dispatch thread never blocks on a per-motion reply.
        Post ops do NOT participate in correlation-id validation (no reply expected)."""
        proc = self._proc
        if proc is None or proc.poll() is not None:
            return False
        with self._lock:
            try:
                proc.stdin.write(json.dumps(req) + "\n")
                proc.stdin.flush()
                return True
            except Exception as e:
                self._diag(f"send error ({req.get('op')}): {e}")
                return False

    # All post ops are fire-and-forget (no round-trip). press()/release() return True
    # optimistically (assumed-success): the backend then stores/clears the gesture
    # binding as usual. Tradeoff (review-flagged): a genuinely-failed post is invisible;
    # a dropped release at worst leaves a stray 'up' (harmless).
    def press(self, pid, wid, psn, win_xy, screen_xy):
        return self._send_noreply(self._req("press", pid, wid, psn, win_xy, screen_xy))

    def release(self, pid, wid, psn, win_xy, screen_xy):
        return self._send_noreply(self._req("release", pid, wid, psn, win_xy, screen_xy))

    def motion(self, pid, wid, psn, win_xy, screen_xy, dragging):
        return self._send_noreply(self._req("motion", pid, wid, psn, win_xy, screen_xy, dragging))

    # ---- teardown -------------------------------------------------------------

    def shutdown(self) -> None:
        """Minimal teardown so tests and process exit leave no helper behind. The full
        lifecycle (respawn/backoff/circuit-breaker, RPC-timeout->kill+respawn) is
        Task 4c.

        Intentionally best-effort and lock-free: clearing `_proc` races a concurrent
        `_rpc`/`_send_noreply`, but the outcome is benign (a concurrent writer hits a
        closed stdin -> caught -> None/False; a blocked reader gets EOF when the child
        is terminated -> unblocks). 4c's lifecycle pass owns proper interlocking."""
        proc = self._proc
        self._proc = None
        self._available = False
        if proc is not None:
            try:
                if proc.stdin:
                    proc.stdin.close()
            except Exception:
                pass
            try:
                proc.terminate()
            except Exception:
                pass
            try:
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        if self._logf not in (None, subprocess.DEVNULL):
            try:
                self._logf.close()
            except Exception:
                pass
        self._logf = None

    # ---- diagnostics ----------------------------------------------------------

    def _diag(self, msg: str) -> None:
        print(f"[inject-remote] {msg}", file=sys.stderr, flush=True)
