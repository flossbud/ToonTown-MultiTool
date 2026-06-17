"""Cross-platform unit tests for _RemoteDelivery's correlation-id read logic AND its
respawn / circuit-breaker / RPC-timeout lifecycle (Task 4c).

The id-validation (discard a stale/late reply from a prior timed-out request, never
misreport it as the current reply) is PURE Python and guards a real desync bug, so it
must run on ALL platforms' CI - NOT gated behind a macOS skip. The module imports cleanly
off-macOS (its PyObjC use is lazy/optional), and `_recv_matching` is driven through an
injectable line-reader, so no real helper or macOS framework is needed.

The lifecycle tests likewise drive a FAKE subprocess (no real helper, no real CLT) and a
monkeypatched clock, so they are pure logic and run cross-platform too.
"""
import json
import subprocess
import threading

import utils.macos_inject_remote as rem


def _bare():
    """A _RemoteDelivery with __init__ (and its spawn) bypassed - only `_recv_matching`,
    which is pure, is exercised."""
    return rem._RemoteDelivery.__new__(rem._RemoteDelivery)


class _FakeStdin:
    def __init__(self):
        self.writes = []
        self.closed = False

    def write(self, b):
        if self.closed:
            raise BrokenPipeError("stdin closed")
        self.writes.append(b)

    def flush(self):
        pass

    def close(self):
        self.closed = True


class _FakeProc:
    """Minimal subprocess.Popen stand-in: poll()/terminate()/kill()/wait() + a stdin,
    with flags so a test can assert the no-zombie reap (terminate/kill followed by wait)."""

    def __init__(self, alive=True):
        self._alive = alive
        self.pid = 4321
        self.stdin = _FakeStdin()
        self.stdout = None
        self.terminated = False
        self.killed = False
        self.waited = False

    def poll(self):
        return None if self._alive else 1

    def terminate(self):
        self.terminated = True
        self._alive = False

    def kill(self):
        self.killed = True
        self._alive = False

    def wait(self, timeout=None):
        self.waited = True
        return 0


def _lifecycle_bare():
    """A _RemoteDelivery with __init__ bypassed but ALL lifecycle attributes set, so the
    respawn/breaker/timeout paths run without a real spawn."""
    d = rem._RemoteDelivery.__new__(rem._RemoteDelivery)
    d._lock = threading.RLock()
    d._proc = None
    d._next_id = 1
    d._available = False
    d._reason = None
    d._ledger = None
    d._logf = None
    d._rbuf = b""
    d._closed = False
    d._consec_failures = 0
    d._circuit_open_until = 0.0
    return d


def test_recv_matching_discards_stale_reply():
    d = _bare()
    awaited = 42
    lines = [
        json.dumps({"ok": True, "id": 7, "stale": True}),       # late reply for a prior req
        json.dumps({"ok": True, "id": awaited, "psn": "ab"}),   # the one we awaited
    ]
    it = iter(lines)

    def fake_read_line(remaining):
        assert remaining > 0
        return next(it, None)

    reply = d._recv_matching(awaited, fake_read_line, timeout=5.0)
    assert reply is not None
    assert reply.get("id") == awaited
    assert reply.get("psn") == "ab"


def test_recv_matching_none_when_only_stale_then_eof():
    d = _bare()
    it = iter([json.dumps({"ok": True, "id": 1}), None])  # stale, then EOF/timeout

    def fake_read_line(remaining):
        return next(it, None)

    # Never return the stale reply; signal None instead of misreporting it as ours.
    assert d._recv_matching(99, fake_read_line, timeout=5.0) is None


def test_recv_matching_skips_unparseable_lines():
    d = _bare()
    it = iter(['{"op":', "[1, 2, 3]", json.dumps({"ok": True, "id": 5})])  # bad json, non-dict, ours

    def fake_read_line(remaining):
        return next(it, None)

    reply = d._recv_matching(5, fake_read_line, timeout=5.0)
    assert reply is not None and reply.get("id") == 5


# ---- lifecycle: circuit breaker / respawn / RPC-timeout (Task 4c) ----------------


def test_circuit_breaker_opens_after_consecutive_failures(monkeypatch):
    """N consecutive spawn/handshake failures OPEN the circuit: further ops short-circuit
    to not-available with `helper-crashed` WITHOUT attempting a spawn, until the cooldown
    elapses. A controlled clock advances past the per-attempt backoff between attempts."""
    clock = {"t": 1000.0}
    monkeypatch.setattr(rem.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(rem.macos_clt, "clt_state", lambda: (True, None, "/fake/clt/python3"))

    spawns = {"n": 0}

    def _always_fail_spawn(self, py, helper):
        spawns["n"] += 1
        return False

    monkeypatch.setattr(rem._RemoteDelivery, "_spawn", _always_fail_spawn)

    d = rem._RemoteDelivery()   # __init__ spawn attempt = failure #1
    try:
        assert d.available is False
        assert d._consec_failures == 1
        assert d.last_reason() == "helper-spawn-failed"
        assert spawns["n"] == 1

        clock["t"] += 100                       # past the inter-attempt backoff
        assert d._maybe_respawn() is False       # failure #2
        assert d._consec_failures == 2
        assert spawns["n"] == 2

        clock["t"] += 100
        assert d._maybe_respawn() is False       # failure #3 -> circuit OPENS
        assert d._consec_failures == rem._CIRCUIT_THRESHOLD
        assert d.last_reason() == "helper-crashed"
        assert spawns["n"] == 3

        # circuit open: respawn short-circuits WITHOUT spawning even though the per-attempt
        # backoff has elapsed (the 30s cooldown gates it).
        clock["t"] += 5                          # still inside the cooldown
        assert d._maybe_respawn() is False
        assert spawns["n"] == 3                   # NOT attempted

        # ops also short-circuit to not-available with helper-crashed, no spawn storm
        assert d.resolve_owner(1) is None
        assert d.press(1, 2, None, (0, 0), (0, 0)) is False
        assert d.motion(1, 2, None, (0, 0), (0, 0), False) is False
        assert spawns["n"] == 3
        assert d.last_reason() == "helper-crashed"

        # after the cooldown elapses, a respawn is attempted afresh
        clock["t"] += rem._CIRCUIT_COOLDOWN_S
        assert d._maybe_respawn() is False        # spawn still failing
        assert spawns["n"] == 4
    finally:
        d.shutdown()


def test_dead_proc_respawn_restores_available(monkeypatch):
    """A dead `_proc` (poll() != None) followed by a SUCCESSFUL respawn restores
    `available`, clears the reason, reaps the prior child, and resets the breaker."""
    monkeypatch.setattr(rem.macos_clt, "clt_state", lambda: (True, None, "/fake/clt/python3"))

    d = _lifecycle_bare()
    dead = _FakeProc(alive=False)
    d._proc = dead
    d._reason = "helper-timeout"
    d._consec_failures = 2

    live = _FakeProc(alive=True)

    def _good_spawn(self, py, helper):
        self._proc = live
        return True

    def _good_handshake(self):
        self._available = True
        self._reason = None
        return True

    monkeypatch.setattr(rem._RemoteDelivery, "_spawn", _good_spawn)
    monkeypatch.setattr(rem._RemoteDelivery, "_handshake", _good_handshake)

    assert d._ensure_alive() is True             # an op on a dead helper respawns it
    assert d.available is True
    assert d.last_reason() is None
    assert d._proc is live
    assert dead.waited is True                   # prior dead child REAPED (no zombie)
    assert d._consec_failures == 0               # success closes the circuit
    assert d._circuit_open_until == 0.0
    d.shutdown()
    assert live.waited is True                   # shutdown reaps the live child too


def test_rpc_timeout_kills_helper_and_latches_helper_timeout(monkeypatch):
    """A synchronous RPC whose reader always times out (helper wedged, still alive) latches
    `helper-timeout`, kills+reaps the child, and arms a backoff so the next op respawns."""
    d = _lifecycle_bare()
    proc = _FakeProc(alive=True)
    d._proc = proc
    d._available = True

    monkeypatch.setattr(d, "_read_line", lambda remaining: None)   # always times out

    assert d.resolve_owner(123) is None
    assert d.last_reason() == "helper-timeout"
    assert proc.terminated is True
    assert proc.waited is True                   # reaped (no zombie)
    assert d._proc is None                        # killed -> respawn deferred to next op
    assert d._available is False
    assert d._circuit_open_until > 0.0            # backoff armed (no tight respawn loop)
    d.shutdown()


def test_rpc_no_helper_returns_none_without_timeout_latch():
    """A clean no-helper / already-dead proc returns None from _rpc WITHOUT latching
    helper-timeout (distinguished from a genuine wedged-helper timeout)."""
    d = _lifecycle_bare()
    d._proc = _FakeProc(alive=False)   # already dead
    d._reason = None
    assert d._rpc("resolve_owner", wid=1) is None
    assert d.last_reason() is None     # NOT helper-timeout


def _no_spawn(self, py, helper):
    raise AssertionError("must NOT spawn")


def test_respawn_handshake_reenters_lock_without_deadlock(monkeypatch):
    """The respawn path holds the RLock across _attempt_spawn -> _try_spawn_handshake ->
    _handshake -> _rpc('hello'), which RE-ACQUIRES the same lock. This verifies the
    reentrancy the RLock (vs a plain Lock) exists for - a regression to threading.Lock
    would self-deadlock here yet pass every other test. Run on a daemon worker with a join
    timeout so a deadlock fails fast instead of hanging the suite."""
    monkeypatch.setattr(rem.macos_clt, "clt_state", lambda: (True, None, "/fake/clt/python3"))

    live = _FakeProc(alive=True)

    def _good_spawn(self, py, helper):
        self._proc = live
        return True

    monkeypatch.setattr(rem._RemoteDelivery, "_spawn", _good_spawn)
    # A REAL _handshake runs (not stubbed): _rpc('hello') re-enters the held lock and reads
    # one valid hello reply through the injected line reader.
    hello = json.dumps({"ok": True, "platform_binary": True, "objc_ok": True,
                        "skylight_ok": True, "id": 1})
    replies = iter([hello])
    monkeypatch.setattr(rem._RemoteDelivery, "_read_line",
                        lambda self, remaining: next(replies, None))

    d = _lifecycle_bare()
    d._proc = _FakeProc(alive=False)   # dead -> an op triggers respawn
    result = {}

    def _run():
        result["ok"] = d._ensure_alive()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=5)
    assert not t.is_alive(), "respawn handshake DEADLOCKED (RLock reentrancy regressed)"
    assert result.get("ok") is True
    assert d.available is True
    d.shutdown()


def test_clt_missing_does_not_escalate_to_helper_crashed(monkeypatch):
    """A missing CLT precondition (no spawn attempted) keeps the actionable `clt-missing`
    reason across repeated respawn attempts and never decays into `helper-crashed`."""
    clock = {"t": 500.0}
    monkeypatch.setattr(rem.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(rem.macos_clt, "clt_state", lambda: (False, "needs CLT", None))
    monkeypatch.setattr(rem._RemoteDelivery, "_spawn", _no_spawn)   # must never spawn

    d = rem._RemoteDelivery()
    try:
        assert d.last_reason() == "clt-missing"
        assert d._consec_failures == 0
        for _ in range(5):
            clock["t"] += rem._CIRCUIT_COOLDOWN_S + 1   # past the cooldown each time
            assert d._maybe_respawn() is False
        assert d._consec_failures == 0                  # never counted toward the breaker
        assert d.last_reason() == "clt-missing"         # NOT overwritten by helper-crashed
    finally:
        d.shutdown()


def test_teardown_escalates_to_kill_when_wait_times_out():
    """If terminate()+wait() does not reap, _teardown_proc escalates to kill()+wait()."""
    class _StubbornProc(_FakeProc):
        def __init__(self):
            super().__init__(alive=True)
            self._first_wait = True

        def wait(self, timeout=None):
            if self._first_wait:
                self._first_wait = False
                raise subprocess.TimeoutExpired(cmd="helper", timeout=timeout)
            super().wait(timeout=timeout)
            return 0

    d = _lifecycle_bare()
    proc = _StubbornProc()
    d._proc = proc
    d._teardown_proc()
    assert proc.terminated is True
    assert proc.killed is True       # escalated after the first wait timed out
    assert d._proc is None


def test_closed_gates_respawn_and_shutdown_is_idempotent(monkeypatch):
    """After shutdown() no op resurrects the helper: _maybe_respawn short-circuits to False
    with no spawn, ops fast-fail, and a second shutdown() is a harmless no-op."""
    monkeypatch.setattr(rem.macos_clt, "clt_state", lambda: (True, None, "/fake/py"))
    spawns = {"n": 0}

    def _count_spawn(self, py, helper):
        spawns["n"] += 1
        self._proc = _FakeProc(alive=True)
        return True

    monkeypatch.setattr(rem._RemoteDelivery, "_spawn", _count_spawn)

    d = _lifecycle_bare()
    d._proc = _FakeProc(alive=True)
    d.shutdown()
    assert d._closed is True
    assert d._maybe_respawn() is False
    assert d.resolve_owner(1) is None
    assert d.press(1, 2, None, (0, 0), (0, 0)) is False
    assert d.motion(1, 2, None, (0, 0), (0, 0), False) is False
    assert spawns["n"] == 0          # closed -> never spawns
    d.shutdown()                     # idempotent: no raise


def test_available_property_respawns_dead_helper(monkeypatch):
    """Reading the `available` property (the readiness surface) on a CRASHED helper triggers
    a respawn (self-healing), so readiness never reports a stale True on a dead helper and a
    crash is recovered on the next readiness probe rather than stranded not-ready."""
    monkeypatch.setattr(rem.macos_clt, "clt_state", lambda: (True, None, "/fake/py"))
    d = _lifecycle_bare()
    d._proc = _FakeProc(alive=False)   # crashed since last op
    live = _FakeProc(alive=True)

    def _good_spawn(self, py, helper):
        self._proc = live
        return True

    def _good_handshake(self):
        self._available = True
        self._reason = None
        return True

    monkeypatch.setattr(rem._RemoteDelivery, "_spawn", _good_spawn)
    monkeypatch.setattr(rem._RemoteDelivery, "_handshake", _good_handshake)

    assert d.available is True        # the property itself respawned the dead helper
    assert d._proc is live


def test_teardown_polls_when_both_waits_time_out():
    """If BOTH the terminate-wait AND the post-kill wait time out, teardown still makes a
    final non-blocking poll() reap attempt (no swallowed-handle zombie) and clears _proc."""
    import subprocess as sp

    class _AlwaysTimeoutWait(_FakeProc):
        def __init__(self):
            super().__init__(alive=True)
            self.polled = False

        def wait(self, timeout=None):
            self.waited = True
            raise sp.TimeoutExpired(cmd="helper", timeout=timeout)

        def poll(self):
            self.polled = True
            return 0

    d = _lifecycle_bare()
    proc = _AlwaysTimeoutWait()
    d._proc = proc
    d._teardown_proc()
    assert proc.terminated is True and proc.killed is True
    assert proc.polled is True        # final last-ditch reap attempt after both waits timed out
    assert d._proc is None


def test_ensure_alive_requires_validated_not_just_live(monkeypatch):
    """A live but UNVALIDATED helper (_available False, e.g. mid spawn/handshake) must NOT
    short-circuit to usable; _ensure_alive routes it to _maybe_respawn so readiness never
    reports an unvalidated child. Once validated, the fast path returns True with no respawn."""
    d = _lifecycle_bare()
    d._proc = _FakeProc(alive=True)
    d._available = False
    called = {"respawn": 0}

    def fake_respawn():
        called["respawn"] += 1
        return False

    monkeypatch.setattr(d, "_maybe_respawn", fake_respawn)
    assert d._ensure_alive() is False     # alive but not validated -> not usable
    assert called["respawn"] == 1         # routed to respawn, not fast-pathed to True

    d._available = True                   # now validated
    assert d._ensure_alive() is True      # fast path
    assert called["respawn"] == 1         # no extra respawn when validated+live
