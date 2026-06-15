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

    def start(self) -> bool:
        with self._lifelock:
            if self._running:
                return True
            self._running = True
            self._died = False
            self._stopping = False
            self._ready.clear()
            self._state.reset()
            self._queue.clear()
            self._dispatcher = threading.Thread(target=self._dispatch_loop,
                                                name="ttmt-cs-dispatch", daemon=True)
            self._dispatcher.start()
            self._native = self._native_factory(self._on_tap_event, self._on_ready,
                                                self._on_native_died)
        if not self._native.start():
            self._teardown()
            return False
        if not self._ready.wait(self._READY_TIMEOUT_S):
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

    def _on_ready(self):
        self._ready.set()

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

    def _on_tap_event(self, cg_type, root_x, root_y, marker, src_pid):
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

    def _dispatch_loop(self):
        while True:
            with self._qcond:
                while not self._queue:
                    self._qcond.wait()
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
