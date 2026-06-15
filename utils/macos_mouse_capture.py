"""Observe-only global mouse capture for Click Sync on macOS (listen-only
CGEventTap). Pure helpers (this section) + the orchestration (Task 5a) + the native CFRunLoop lifecycle (Task 5b).

Emits the XRecordCapture contract: on_event(kind, root_x, root_y, state, time_ms)
with kind in 'press' | 'release' | 'motion' and `state` the X-style button mask -
synthesized with X semantics like utils/win32_mouse_capture.py (a press excludes its
own button, a release includes it). The pure helpers carry NO PyObjC import.
"""
from __future__ import annotations

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
