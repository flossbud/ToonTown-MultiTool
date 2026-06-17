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

Lifecycle (Task 4c): when an op finds the helper dead it attempts a respawn,
bounded by a circuit breaker - after N consecutive spawn/handshake failures the
circuit OPENS for a cooldown (stays not-available, reason `helper-crashed`) so a
tight motion loop cannot storm respawns; a successful respawn closes it. A
synchronous RPC that times out (the reader is deadline-bounded) treats the helper
as wedged: it latches `helper-timeout`, kills+reaps the child, and a short backoff
defers the respawn to the next op. Every kill is followed by a wait() (reap), and a
respawn reaps the prior child first, so no zombie accumulates.
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

# Circuit breaker: after this many CONSECUTIVE spawn/handshake failures, OPEN the
# circuit (stop respawning, report `helper-crashed`) for the cooldown. A successful
# respawn resets the count and closes it. "Consecutive" + reset-on-success gives the
# "within a short window" semantics: a success between failures clears the count, and
# the per-attempt backoff naturally clusters consecutive attempts into a short span.
_CIRCUIT_THRESHOLD = 3
_CIRCUIT_COOLDOWN_S = 30.0
# Bounded backoff deferred before the NEXT respawn after a sub-threshold spawn failure
# OR an RPC-timeout kill. This is the rate-limit that stops a 60Hz hover/drag stream
# from respawning on every motion event (the circuit cooldown handles the give-up case).
_RESPAWN_BACKOFF_S = 1.0

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
        # RLock (not Lock): a respawn holds the lock across spawn+handshake, and the
        # handshake's _rpc("hello") re-acquires it - reentrancy avoids a self-deadlock.
        self._lock = threading.RLock()
        self._proc = None
        self._next_id = 1
        self._available = False
        self._reason: str | None = None
        # Accepted for signature parity with the in-process engine, and INTENTIONALLY
        # UNUSED. Two independent reasons it cannot be wired through to record echoes:
        #   1. The helper posts in its OWN process and runs its OWN delivery engine, so
        #      it physically cannot record into THIS app-process EchoLedger instance.
        #   2. The per-window SkyLight SLEventPostToPid path delivers an event ONLY into
        #      the target PID's event queue; it does NOT re-enter the app's global
        #      capture tap (which observes the session/HID stream), so the capture's
        #      marker-stripped-echo guard never sees a helper-posted event in the first
        #      place - there is nothing to record.
        # LIVE-VALIDATION FLAG: if a future build shows an echo loop on the helper path
        # (a posted event re-entering the capture), revisit assumption (2).
        self._ledger = ledger
        self._logf = None
        self._rbuf = b""   # byte buffer for the deadline-bounded line reader
        # ---- lifecycle / circuit-breaker state (all guarded by _lock) ----
        self._closed = False             # shutdown() latches this; gates all respawns
        self._consec_failures = 0        # consecutive spawn/handshake failures
        self._circuit_open_until = 0.0   # monotonic deadline; now < this => respawn gated
        with self._lock:
            self._attempt_spawn(time.monotonic())

    # ---- spawn + handshake ----------------------------------------------------

    def _attempt_spawn(self, now: float) -> bool:
        """Reap any prior child, then spawn+handshake ONCE, updating the breaker. Caller
        holds _lock. Returns True iff the helper is now available. On failure, advances
        the consecutive-failure count and arms a backoff (or, at the threshold, opens the
        circuit for the cooldown and latches `helper-crashed`)."""
        self._teardown_proc()   # reap a prior dead child first (no zombie across respawn)
        if self._try_spawn_handshake():
            self._consec_failures = 0
            self._circuit_open_until = 0.0
            return True
        self._consec_failures += 1
        if self._consec_failures >= _CIRCUIT_THRESHOLD:
            self._circuit_open_until = now + _CIRCUIT_COOLDOWN_S
            self._reason = "helper-crashed"   # circuit OPEN: give up for the cooldown
        else:
            self._circuit_open_until = now + _RESPAWN_BACKOFF_S   # bounded inter-attempt backoff
        return False

    def _try_spawn_handshake(self) -> bool:
        """Spawn the CLT python helper and validate it with a `hello` handshake. On
        success: `_available` True, `_reason` None, returns True. On failure: latches a
        single reason, tears down (reaps) any spawned-but-unusable child, returns False.
        Does NOT touch the breaker (the caller owns that)."""
        ok, _reason, clt_python = macos_clt.clt_state()
        if not (ok and clt_python):
            # CLT absent: do NOT spawn (spawning /usr/bin/python3 with no developer dir
            # would pop the Xcode installer). Latch and stay unavailable.
            self._reason = "clt-missing"
            return False
        helper = _helper_path()
        if not self._spawn(clt_python, helper):
            self._reason = "helper-spawn-failed"
            return False
        self._rbuf = b""   # fresh reader buffer for the new child
        if not self._handshake():
            # Spawned but unusable (wrong identity / objc / skylight / no reply). The
            # child is otherwise healthy and would block on stdin forever, so reap it NOW
            # rather than leak a resident helper + pipes + logfile. _teardown_proc()
            # preserves the latched reason.
            self._teardown_proc()
            return False
        return True

    def _spawn(self, clt_python: str, helper_path: str) -> bool:
        try:
            log_path = _helper_log_path()
            os.makedirs(os.path.dirname(log_path), exist_ok=True)  # don't depend on main.py import order
            self._logf = open(log_path, "a", buffering=1)
        except Exception:
            self._logf = subprocess.DEVNULL
        try:
            # Binary, unbuffered: replies are read via select+os.read on the fd into a
            # deadline-bounded buffer (see _read_line), so a partial/stalled line can
            # never block past the RPC timeout. Requests are written as encoded bytes.
            self._proc = subprocess.Popen(
                [clt_python, "-s", helper_path],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._logf,
                env=dict(_SCRUBBED_ENV), bufsize=0,
            )
            self._diag(f"spawned platform-binary helper {clt_python} -s {helper_path} "
                       f"pid={self._proc.pid}")
            return True
        except Exception as e:
            self._diag(f"FAILED to spawn helper {clt_python} -s {helper_path}: {e}")
            self._proc = None
            self._close_logf()   # don't leak the logfile fd when the spawn fails
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

    # ---- respawn lifecycle ----------------------------------------------------

    def _proc_alive(self) -> bool:
        """True iff a child exists and has not exited. Lock-free + cheap (a waitpid
        WNOHANG via Popen.poll), so the per-motion liveness check costs nothing on the
        healthy path."""
        proc = self._proc
        return proc is not None and proc.poll() is None

    def _ensure_alive(self) -> bool:
        """Fast path for every op: alive -> True with no lock. Dead -> attempt a respawn
        (gated by the circuit breaker / backoff). Returns whether a usable helper exists."""
        if self._proc_alive():
            return True
        return self._maybe_respawn()

    def _maybe_respawn(self) -> bool:
        """Respawn a dead helper, subject to the circuit breaker. Returns True iff a live,
        validated helper exists afterwards. Rate-limited: while the circuit is open (or
        within the inter-attempt backoff) this short-circuits WITHOUT spawning, so a tight
        motion loop can never storm respawns."""
        with self._lock:
            if self._closed:
                return False
            if self._proc_alive():
                return True   # another thread already respawned while we waited on the lock
            now = time.monotonic()
            if now < self._circuit_open_until:
                return False  # circuit OPEN (helper-crashed) or inter-attempt backoff
            return self._attempt_spawn(now)

    # ---- RPC ------------------------------------------------------------------

    def _read_line(self, remaining: float):
        """Return one complete decoded reply line (newline stripped), or None on timeout
        / EOF (helper gone). DEADLINE-BOUNDED: reads raw bytes via select+os.read into a
        persistent buffer, so a partial line from a stalled/truncated helper can NEVER
        block past the timeout. (A plain readline() after select() would block waiting for
        the newline, holding the lock and defeating the RPC-timeout->kill.) Leftover
        bytes after a line stay buffered for the next call."""
        proc = self._proc
        if proc is None or proc.stdout is None:
            return None
        deadline = time.monotonic() + max(0.0, remaining)
        while True:
            nl = self._rbuf.find(b"\n")
            if nl >= 0:
                line = self._rbuf[:nl]
                self._rbuf = self._rbuf[nl + 1:]
                return line.decode("utf-8", "replace")
            rem = deadline - time.monotonic()
            if rem <= 0:
                return None
            try:
                ready, _, _ = select.select([proc.stdout], [], [], rem)
            except Exception:
                return None
            if not ready:
                return None
            try:
                chunk = os.read(proc.stdout.fileno(), 65536)
            except Exception:
                return None
            if not chunk:
                return None  # EOF: helper gone
            self._rbuf += chunk

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
        matching reply dict, or None on no-helper / write-error / timeout. On a genuine
        TIMEOUT (the child is still alive but did not reply) the helper is treated as
        wedged: latch `helper-timeout`, kill+reap it, and arm a backoff so the NEXT op
        respawns (not a tight loop)."""
        with self._lock:
            proc = self._proc
            if proc is None or proc.poll() is not None:
                return None   # clean no-helper / already-dead: no timeout latch
            req_id = self._next_id
            self._next_id += 1
            req = {"op": op, "id": req_id, **fields}
            try:
                proc.stdin.write((json.dumps(req) + "\n").encode("utf-8"))
                proc.stdin.flush()
            except Exception as e:
                self._diag(f"RPC write error ({op}): {e}")
                return None
            reply = self._recv_matching(req_id, self._read_line, _RPC_TIMEOUT_S)
            if reply is not None:
                return reply
            # No reply within the deadline. A child that DIED mid-call (poll() != None) is
            # a crash, left for the next op's _maybe_respawn (which may open the circuit ->
            # helper-crashed). A child STILL ALIVE is genuinely wedged -> kill+reap it.
            if proc.poll() is None:
                self._diag(f"RPC timeout ({op}); killing wedged helper for respawn")
                self._reason = "helper-timeout"
                self._teardown_proc()
                self._circuit_open_until = time.monotonic() + _RESPAWN_BACKOFF_S
            return None

    # ---- public surface -------------------------------------------------------

    @property
    def available(self) -> bool:
        return self._available

    def last_reason(self) -> str | None:
        return self._reason

    def resolve_psn(self, wid):
        if not self._ensure_alive():
            return None
        r = self._rpc("resolve_psn", wid=int(wid))
        if not (r and r.get("ok")):
            return None
        h = r.get("psn") or ""
        return bytes.fromhex(h) if h else None

    def resolve_owner(self, wid):
        if not self._ensure_alive():
            return None
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
        Post ops do NOT participate in correlation-id validation (no reply expected). A
        write to a dead/closed pipe is caught -> False; the next op's _ensure_alive then
        respawns."""
        with self._lock:
            proc = self._proc
            if proc is None or proc.poll() is not None:
                return False
            try:
                proc.stdin.write((json.dumps(req) + "\n").encode("utf-8"))
                proc.stdin.flush()
                return True
            except Exception as e:
                self._diag(f"send error ({req.get('op')}): {e}")
                return False

    # All post ops are fire-and-forget (no round-trip). press()/release() return True
    # optimistically (assumed-success) when a live helper exists: the backend then
    # stores/clears the gesture binding as usual. A dead helper that cannot be respawned
    # (circuit open / backoff) returns False so the backend never binds an undeliverable
    # gesture. Tradeoff (review-flagged): a genuinely-failed post is invisible; a dropped
    # release at worst leaves a stray 'up' (harmless).
    def press(self, pid, wid, psn, win_xy, screen_xy):
        if not self._ensure_alive():
            return False
        return self._send_noreply(self._req("press", pid, wid, psn, win_xy, screen_xy))

    def release(self, pid, wid, psn, win_xy, screen_xy):
        if not self._ensure_alive():
            return False
        return self._send_noreply(self._req("release", pid, wid, psn, win_xy, screen_xy))

    def motion(self, pid, wid, psn, win_xy, screen_xy, dragging):
        if not self._ensure_alive():
            return False
        return self._send_noreply(self._req("motion", pid, wid, psn, win_xy, screen_xy, dragging))

    # ---- teardown -------------------------------------------------------------

    def shutdown(self) -> None:
        """Permanent teardown: latch `_closed` (no further respawns), then reap the child
        and release pipes + logfile. Idempotent. Under _lock so it interlocks with a
        concurrent op/respawn (the RLock is reentrant; _teardown_proc never re-acquires)."""
        with self._lock:
            self._closed = True
            self._teardown_proc()

    def _teardown_proc(self) -> None:
        """Reap the current child (terminate -> wait; escalate to kill -> wait) and clear
        the proc/available/reader state + close the captured-stderr logfile. EVERY kill is
        followed by a wait() so no zombie is left behind, and a respawn calls this first so
        the prior child is reaped before a new one starts. Lock-free: the caller owns
        _lock. Preserves `_reason` and the breaker counters (so a respawn keeps the latch)."""
        proc = self._proc
        self._proc = None
        self._available = False
        self._rbuf = b""   # discard any partial bytes from the dead child
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
                proc.wait(timeout=2)   # reap after terminate
            except Exception:
                try:
                    proc.kill()
                    proc.wait(timeout=2)   # reap after kill so we don't leave a zombie
                except Exception:
                    pass
        self._close_logf()

    def _close_logf(self) -> None:
        """Close the captured-stderr logfile if we own a real handle (not None/DEVNULL)."""
        if self._logf not in (None, subprocess.DEVNULL):
            try:
                self._logf.close()
            except Exception:
                pass
        self._logf = None

    # ---- diagnostics ----------------------------------------------------------

    def _diag(self, msg: str) -> None:
        print(f"[inject-remote] {msg}", file=sys.stderr, flush=True)
