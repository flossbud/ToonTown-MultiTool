"""Observe-only global mouse capture for Click Sync on macOS (listen-only
CGEventTap). Pure helpers (this section) + the orchestration (Task 5a) + the native CFRunLoop lifecycle (Task 5b).

Emits the XRecordCapture contract: on_event(kind, root_x, root_y, state, time_ms)
with kind in 'press' | 'release' | 'motion' and `state` the X-style button mask -
synthesized with X semantics like utils/win32_mouse_capture.py (a press excludes its
own button, a release includes it). The pure helpers carry NO PyObjC import.
"""
from __future__ import annotations

import threading
from time import monotonic

from utils.macos_mouse_delivery import SPIKE_EVENT_TAG, EchoLedger

# X-style button masks (Button1Mask..Button5Mask) - the service's lingua franca.
_X_BUTTON_MASK = {1: 0x100, 2: 0x200, 3: 0x400, 4: 0x800, 5: 0x1000}

# CGEventType (int) -> (action, x-button-number). "other" maps to middle (2): the
# service only distinguishes Button1 (drag) from any-held (hover suppression).
_CG_EVENT = {
    1: ("down", 1), 2: ("up", 1),          # left down/up
    3: ("down", 3), 4: ("up", 3),          # right down/up
    5: ("move", None), 6: ("move", 1), 7: ("move", 3),  # moved / left-drag / right-drag
    25: ("down", 2), 26: ("up", 2), 27: ("move", 2),    # other down/up/drag
}

# Echo circuit-breaker tunables (spec §3.3). The signature TTL lives on EchoLedger.
ECHO_WINDOW_S = 0.500
ECHO_TRIP = 24


def mask_for(held) -> int:
    m = 0
    for b in held:
        m |= _X_BUTTON_MASK.get(b, 0)
    return m


def classify_event(cg_type):
    """CGEventType int -> (action in {'down','up','move'} | None, x-button | None)."""
    return _CG_EVENT.get(int(cg_type), (None, None))


def reenable_decision(count, max_reenable, enabled_after) -> str:
    """After a tap-disable re-enable attempt, decide "stop" or "retry" (pure/testable).

    `count` = consecutive-disable count (post-increment); `max_reenable` = the flap bound;
    `enabled_after` = whether CGEventTapIsEnabled is True after the re-enable (None if it
    could not be verified). A VERIFIED-failed re-enable (enabled_after is False) must STOP
    NOW: a disabled tap emits no further callbacks, so waiting for `count` to reach the
    bound would hang silently and on_died would never fire. Too many flaps (count >
    max_reenable) also stops. Otherwise retry (re-enabled OK, or could not verify)."""
    if count > max_reenable:
        return "stop"
    if enabled_after is False:
        return "stop"
    return "retry"


class ButtonState:
    """X-semantics held-button tracker (a press excludes its own button, a release
    includes it). Not thread-safe on its own; the capture serializes access."""
    def __init__(self):
        self._held = set()

    def on_down(self, button) -> int:
        state = mask_for(self._held)   # excludes itself
        self._held.add(button)
        return state

    def on_up(self, button) -> int:
        self._held.add(button)         # defensive: unseen press
        state = mask_for(self._held)   # includes itself
        self._held.discard(button)
        return state

    def on_move(self) -> int:
        return mask_for(self._held)

    def reset(self):
        self._held.clear()


class EchoGuard:
    """Recognizes our own posted events so the capture can filter them, and trips a
    STICKY circuit breaker ONLY on apparent marker-stripped recursion (a signature
    match with our marker ABSENT). Correctly-marked events are filtered but NEVER
    counted, so ordinary 60Hz marked motion cannot trip the breaker - but a future
    marker-stripping OS revision still cannot sustain a fan-out loop (spec §3.3).

    Shares the SAME `EchoLedger` instance the delivery engine records posts into, so
    the recent-post signatures it matches against are exactly what we sent."""
    def __init__(self, ledger, own_pid, now=None):
        self._ledger = ledger          # the SAME EchoLedger the delivery engine writes to
        self._own_pid = own_pid
        self._now = now or monotonic
        self._hits = []                # timestamps of marker-stripped echoes (breaker input)
        self._tripped = False

    def is_synthetic(self, cg_type, root_x, root_y, marker, src_pid) -> bool:
        """True if this captured event is one of OUR posts (the caller filters it)."""
        if marker == SPIKE_EVENT_TAG:
            return True                # correctly marked -> filter, do NOT count
        if src_pid is not None and src_pid == self._own_pid:
            return True                # our own source pid -> filter, do NOT count
        if self._ledger is not None and self._ledger.matches(cg_type, root_x, root_y, now=self._now()):
            self._note_stripped()      # marker-STRIPPED echo of a recent post -> filter AND count
            return True
        return False                   # a genuine user event

    def _note_stripped(self) -> None:
        t = self._now()
        self._hits = [ts for ts in self._hits if t - ts <= ECHO_WINDOW_S]
        self._hits.append(t)
        if len(self._hits) > ECHO_TRIP:
            self._tripped = True       # sticky

    @property
    def tripped(self) -> bool:
        return self._tripped


# ── capture orchestration (bounded queue + dispatcher thread) ───────────────────
import collections
import os

_SENTINEL = object()


class MacOSMouseCapture:
    """Listen-only CGEventTap capture. The tap callback only filters + classifies +
    enqueues; a dispatcher thread delivers on_event. start()->bool, stop()
    (idempotent, any thread), is_running(). on_died fires at most once on an
    UNEXPECTED end (tap-create fail / runloop death / dispatcher death / echo breaker);
    a clean stop() does NOT fire it. `native_factory` is injectable for tests."""

    _READY_TIMEOUT_S = 2.0
    MAX_QUEUE = 4096   # bound: on overload we kill capture (never silently drop a release)

    def __init__(self, on_event, on_died=None, *, ledger=None, own_pid=None, native_factory=None):
        self._on_event = on_event
        self._on_died = on_died
        self._own_pid = own_pid if own_pid is not None else os.getpid()
        self._native_factory = native_factory or self._default_native
        self._state = ButtonState()
        # Shares the SAME EchoLedger the delivery engine records posts into (wired by the
        # tab, Task 8). None in a standalone capture -> only marker/own-pid filtering.
        self._guard = EchoGuard(ledger, self._own_pid)
        self._queue = collections.deque()
        self._qcond = threading.Condition(threading.Lock())
        self._lifelock = threading.Lock()
        self._running = False
        self._died = False
        self._stopping = False
        self._ready = threading.Event()
        self._native = None
        self._dispatcher = None
        self._generation = 0

    def start(self) -> bool:
        """Start capture. NOTE: start()/stop() are NOT safe to call CONCURRENTLY from
        multiple threads - the owner (the tab/service) calls them serially on one thread.
        The only cross-thread call supported is stop() from a death callback (handled by
        the self-join guard). Within that contract this is race-free."""
        with self._lifelock:
            if self._running:
                return True
            # Bump the generation as the VERY FIRST mutation so a stale callback/dispatcher
            # from a previous run sees gen != self._generation and no-ops (closes the
            # window between the per-run setup and the bump).
            self._generation += 1
            gen = self._generation
            self._running = True
            self._died = False
            self._stopping = False
            self._state.reset()
            # A FRESH per-run readiness event, captured locally: a stale run's callback can
            # never satisfy THIS run's wait, nor can a new run's readiness satisfy an old
            # wait (each run waits on its own event).
            ready = threading.Event()
            self._ready = ready
            self._dispatcher = threading.Thread(target=self._dispatch_loop, args=(gen,),
                                                name="ttmt-cs-dispatch", daemon=True)
            dispatcher = self._dispatcher           # local: immune to a concurrent null-out
            # Each native callback is generation-guarded; the ready callback sets THIS run's
            # event directly (not a shared field) so a stale ready cannot leak across runs.
            def _tap_cb(*args):
                if gen == self._generation:
                    self._on_tap_event(*args)
            def _ready_cb():
                if gen == self._generation:
                    ready.set()
            def _died_cb():
                if gen == self._generation:
                    self._on_native_died()
            self._native = self._native_factory(_tap_cb, _ready_cb, _died_cb)
            native = self._native                   # local: immune to a concurrent null-out
        # Clear the queue (dropping any stale SENTINEL left by a previous timed-out join) and
        # wake any orphaned old-gen dispatcher to re-check its generation and exit - BEFORE
        # starting the NEW dispatcher, so the new dispatcher can never consume an old sentinel
        # (which would silently blackout event delivery).
        with self._qcond:
            self._queue.clear()
            self._qcond.notify_all()
        dispatcher.start()
        if not native.start():
            self._teardown()
            return False
        if not ready.wait(self._READY_TIMEOUT_S):
            self._teardown()
            return False
        return True

    def stop(self) -> None:
        self._teardown()

    def is_running(self) -> bool:
        with self._lifelock:
            if not self._running or self._native is None:
                return False
            native = self._native
        return bool(native.is_alive())

    def _teardown(self):
        with self._lifelock:
            if not self._running and self._native is None and self._dispatcher is None:
                return
            self._running = False
            self._stopping = True
            native, self._native = self._native, None
            dispatcher, self._dispatcher = self._dispatcher, None
        with self._qcond:
            self._queue.append(_SENTINEL)
            self._qcond.notify_all()
        if native is not None:
            try:
                native.stop()
            except Exception:
                pass
        cur = threading.current_thread()
        if dispatcher is not None and dispatcher is not cur and dispatcher.is_alive():
            dispatcher.join(timeout=1.0)

    def _on_native_died(self):
        self._die()

    def _die(self):
        with self._lifelock:
            if self._died or self._stopping:
                return   # already dying, or a clean stop is in progress
            self._died = True
        self._teardown()
        if self._on_died is not None:
            try:
                self._on_died()
            except Exception:
                pass

    def _on_tap_event(self, cg_type, root_x, root_y, marker, src_pid,
                      evt_ns: int = 0):
        """Runs on the runloop thread - MUST stay fast: filter, classify, enqueue."""
        try:
            if self._guard.is_synthetic(cg_type, root_x, root_y, marker, src_pid):
                if self._guard.tripped:
                    self._die()                 # echo circuit breaker tripped (marker-stripped flood)
                return                          # filtered: never mutate held / enqueue
            action, button = classify_event(cg_type)
            if action is None:
                return
            t = self._now_ms()
            if evt_ns:
                # Prefer the kernel generation stamp (same since-boot basis
                # as monotonic on macOS). Defensive basis check: a unit
                # surprise (raw mach ticks on some chips) diverges from the
                # callback stamp immediately - beyond 5s, keep the callback
                # stamp (auto-degrade to pre-dejitter behavior).
                evt_ms = evt_ns // 1_000_000
                if abs(evt_ms - t) <= 5000:
                    t = int(evt_ms)
            overflowed = False
            if action == "down":
                state = self._state.on_down(button)
                if button == 1:
                    overflowed = self._enqueue(("press", int(root_x), int(root_y), state, t))
            elif action == "up":
                state = self._state.on_up(button)
                if button == 1:
                    overflowed = self._enqueue(("release", int(root_x), int(root_y), state, t))
            else:  # move (incl. dragged)
                overflowed = self._enqueue(("motion", int(root_x), int(root_y), self._state.on_move(), t))
            if overflowed:
                self._die()                     # queue overload: stop capture, let the dispatcher drain
        except Exception:
            self._die()

    def _enqueue(self, item) -> bool:
        """Enqueue for the dispatcher. Coalesces ONLY consecutive motion (so motion
        cannot grow the queue unbounded). Returns True if the queue OVERFLOWED - the
        item is still kept (a press/release is never silently dropped) and the caller
        kills capture so the dispatcher can drain what is queued."""
        with self._qcond:
            if item[0] == "motion" and self._queue and self._queue[-1][0] == "motion":
                self._queue[-1] = item          # coalesce consecutive motion only
                self._qcond.notify()
                return False
            overflow = len(self._queue) >= self.MAX_QUEUE
            self._queue.append(item)            # keep it even on overflow (never drop a release)
            self._qcond.notify()
            return overflow

    def _dispatch_loop(self, gen):
        while True:
            with self._qcond:
                while not self._queue:
                    # Exit immediately if our generation is stale (a new start()
                    # has run).  We must check inside _qcond so we see any
                    # notify_all() that start() fires after clearing the queue.
                    if gen != self._generation:
                        return
                    self._qcond.wait()
                # Check again after waking (start() may have bumped generation
                # and cleared the queue between the notify and our re-acquire).
                if gen != self._generation:
                    return
                item = self._queue.popleft()
            if item is _SENTINEL:
                return
            try:
                self._on_event(*item)
            except Exception:
                self._die()
                return

    @staticmethod
    def _now_ms() -> int:
        return int(monotonic() * 1000)

    @staticmethod
    def _default_native(on_tap_event, on_ready, on_died):
        return _QuartzTapNative(on_tap_event, on_ready, on_died)


class _QuartzTapNative:
    """Real listen-only CGEventTap + CFRunLoop on a dedicated thread. OPERATOR/LIVE-
    validated (Task 9), not unit-tested against real PyObjC. The capture drives all
    state through the three callbacks; this class only owns the tap + runloop.

    Lifecycle contract: on a STARTUP failure (source/tap-enable raising) on_died may fire
    WITHOUT a preceding on_ready; the owner (MacOSMouseCapture) treats that as a failed
    start (its readiness wait times out) and tears down - it does not assume a strict
    on_ready->on_died ordering."""

    _MASK_TYPES = (1, 2, 3, 4, 5, 6, 7, 25, 26, 27)  # left/right/other down/up/drag + moved
    _MAX_REENABLE = 5   # consecutive tap-disable re-enables before giving up -> on_died

    def __init__(self, on_tap_event, on_ready, on_died):
        self._on_tap_event = on_tap_event
        self._on_ready = on_ready
        self._on_died = on_died
        self._thread = None
        self._runloop = None
        self._tap = None
        self._src = None
        self._cb = None
        self._reenable_count = 0   # consecutive disables since the last good event
        # Published by _run() once CFRunLoopGetCurrent() is captured, so stop() can ALWAYS
        # obtain the runloop ref to wake it (closes the start-thread -> runloop-capture window
        # where a stop() would otherwise miss the runloop and leak a spinning thread + tap).
        self._rl_ready = threading.Event()
        self._stop_requested = False

    def start(self) -> bool:
        import Quartz
        preflight = getattr(Quartz, "CGPreflightListenEventAccess", None)
        if preflight is not None and not preflight():
            return False
        mask = 0
        for t in self._MASK_TYPES:
            mask |= Quartz.CGEventMaskBit(t)

        def _cb(proxy, etype, event, refcon):
            try:
                if etype in (Quartz.kCGEventTapDisabledByTimeout,
                             Quartz.kCGEventTapDisabledByUserInput):
                    # Re-enable + VERIFY. A verified-failed re-enable stops NOW (a dead tap
                    # emits no further callbacks, so waiting for the flap bound would hang
                    # silently); too many flaps also stops. Either way _run's finally fires
                    # on_died - we never silently loop or hang on a dead tap.
                    self._reenable_count += 1
                    enabled_after = None
                    if self._tap is not None and self._reenable_count <= self._MAX_REENABLE:
                        Quartz.CGEventTapEnable(self._tap, True)
                        is_enabled = getattr(Quartz, "CGEventTapIsEnabled", None)
                        if is_enabled is not None:
                            enabled_after = bool(is_enabled(self._tap))
                    if reenable_decision(self._reenable_count, self._MAX_REENABLE,
                                         enabled_after) == "stop" and self._runloop is not None:
                        Quartz.CFRunLoopStop(self._runloop)
                    return event
                loc = Quartz.CGEventGetLocation(event)
                marker = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGEventSourceUserData)
                pid = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGEventSourceUnixProcessID)
                self._reenable_count = 0   # a good event resets the disable streak
                # Kernel-stamped GENERATION time (ns, since-boot - the same
                # basis as time.monotonic() on macOS). The callback itself
                # needs the GIL, so stamping "now" here bunches timestamps
                # whenever the process stalls; the event's own stamp is
                # immune and lets the ghost renderer replay the true motion
                # timeline (dejitter).
                evt_ns = Quartz.CGEventGetTimestamp(event)
                self._on_tap_event(int(etype), float(loc.x), float(loc.y),
                                   int(marker), int(pid) or None, int(evt_ns))
            except Exception:
                pass
            return event

        self._tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap, Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionListenOnly, mask, _cb, None)
        if self._tap is None:
            return False
        self._cb = _cb   # retain
        self._thread = threading.Thread(target=self._run, name="ttmt-cs-runloop", daemon=True)
        self._thread.start()
        return True

    def _run(self):
        import Quartz
        try:
            self._runloop = Quartz.CFRunLoopGetCurrent()
            self._rl_ready.set()                 # publish the runloop ref BEFORE running
            if self._stop_requested:             # a stop() raced in before we started running
                return
            self._src = Quartz.CFMachPortCreateRunLoopSource(None, self._tap, 0)
            Quartz.CFRunLoopAddSource(self._runloop, self._src, Quartz.kCFRunLoopCommonModes)
            Quartz.CGEventTapEnable(self._tap, True)
            self._on_ready()
            Quartz.CFRunLoopRun()
        except Exception as e:
            # startup/runloop failure: surface it (don't silently swallow) - on_died fires
            # in the finally (may be WITHOUT a prior on_ready; see the class contract).
            print(f"[macos_mouse_capture] _QuartzTapNative run error: {type(e).__name__}: {e}")
        finally:
            try:
                if self._runloop is not None and self._src is not None:
                    Quartz.CFRunLoopRemoveSource(self._runloop, self._src, Quartz.kCFRunLoopCommonModes)
            except Exception:
                pass
            try:
                Quartz.CFMachPortInvalidate(self._tap)
            except Exception:
                pass
            self._on_died()

    def stop(self) -> None:
        import Quartz
        self._stop_requested = True
        th = self._thread
        if th is not None:
            # Wait for _run() to publish the runloop ref so CFRunLoopStop can't miss it (the
            # start-thread -> runloop-capture window). Bounded so a wedged startup can't hang.
            self._rl_ready.wait(2.0)
        rl = self._runloop
        if rl is not None:
            try:
                Quartz.CFRunLoopStop(rl)   # cross-thread wake; safe from any thread
            except Exception:
                pass
        # Deterministic join, self-join-safe: if stop() is called FROM the runloop thread
        # (e.g. the echo breaker / overflow path inside the tap callback), skip the join.
        if th is not None and th is not threading.current_thread() and th.is_alive():
            th.join(timeout=2.0)

    def is_alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())
