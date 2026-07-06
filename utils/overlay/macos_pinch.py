"""macOS pinch wire layer for the Float UI trackpad pinch-to-zoom.

Phase 2 of docs/superpowers/specs/2026-07-05-trackpad-pinch-zoom-design.md.
This module holds the PURE half of the macOS translator: a per-event CGEvent
field decoder plus the factor-stream normalizer that feeds the coordinator's
on_begin / on_update(abs_factor) / on_end(cancelled) callback contract
(utils/overlay/pinch_zoom.py). The CGEventTap glue (MacOSPinchTranslator)
lands beside these in a follow-on task; Quartz is imported ONLY there, at
call time - this file stays importable on every platform (pinned by the
suite's subprocess purity test).

Wire format - probe-decoded and BINDING, per the CP-P1 run-3 verdict in
docs/superpowers/specs/2026-07-05-pinch-zoom-probe-ledger.md (fixtures under
tests/fixtures/pinch/ are wholesale copies of that capture; never re-derive
from lore - NSEvent.eventWithCGEvent DROPS magnification, so raw fields are
the only truth):

- cgType 29 (gesture family): a pinch iff int field 110 == 8; double field
  113 is the per-event magnification delta (NSEvent scale, positive =
  fingers apart). Other observed subtypes (4/5/6/32) and subtype-less
  family events are noise and decode to None.
- cgType 30 (rare magnify variant, 1 of 19 captured gestures): double field
  124 is CUMULATIVE magnification since gesture begin; per-event deltas are
  successive differences, with the baseline reset to 0.0 at Began. No
  subtype gate here: field 110 read 23 on the single observed gesture, but
  cgType+d124 is the defining signature and pinning one capture's subtype
  would overfit.
- int field 132 is the phase: 1=Began, 2=Changed, 4=Ended. Cancelled was
  never observed live, so ANY other nonzero phase maps to CANCEL ->
  on_end(cancelled=True): an unknown phase must terminate, and a
  termination on unvetted evidence must not snap (the machine's cancel
  semantics). Phase 0/missing is not a gesture event at all.
- Ended events CARRY a final delta (observed nonzero): it is applied to the
  factor AND published via on_update BEFORE on_end fires, else the machine
  would commit a scale one event stale.
- Normalization: abs_factor resets to 1.0 at Began and multiplies by
  (1.0 + delta) per event - the Began event's own delta applies too (run 3
  shows real nonzero Began deltas), mirroring AppKit's accumulation.
- Orphan Changed/Ended/Cancelled with no open gesture are dropped silently:
  the coordinator/machine already define stray updates as no-ops, and
  opening a gesture from partial evidence would bypass the coordinator's
  begin gate. A tap enabled mid-gesture therefore loses that gesture's
  tail; the next physical gesture begins cleanly.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable, Optional

# backend.py is os/sys only (its Qt/native backends load lazily inside a
# function), so this import keeps the module Qt- AND Quartz-free at top level
# - the subprocess purity test still passes. overlay_trace is the same silent-
# unless-TTMT_OVERLAY_TRACE stamp the coordinator uses.
from utils.overlay.backend import overlay_trace

# CGEvent numeric types and field numbers (probe ledger table). The tap glue
# and the fixtures both speak these raw numbers - there are no public Quartz
# constants for the gesture-family fields.
CG_TYPE_GESTURE = 29   # gesture family: subtype in field 110
CG_TYPE_MAGNIFY = 30   # rare dedicated-magnify variant
FIELD_SUBTYPE = 110    # int: gesture subtype on CG_TYPE_GESTURE events
SUBTYPE_ZOOM = 8
FIELD_DELTA = 113      # double: per-event magnification delta (type 29)
FIELD_CUMULATIVE = 124  # double: cumulative magnification (type 30)
FIELD_PHASE = 132      # int: gesture phase
PHASE_BEGAN = 1
PHASE_CHANGED = 2
PHASE_ENDED = 4


class PinchKind(Enum):
    BEGIN = auto()   # phase Began (carries its own first delta)
    DELTA = auto()   # phase Changed
    END = auto()     # phase Ended (carries a final delta)
    CANCEL = auto()  # any other nonzero phase - conservative termination


@dataclass(frozen=True)
class PinchEvent:
    """One decoded pinch wire event.

    ``value`` is the per-event delta for the cgType-29 representation, or
    the cumulative-since-begin magnification when ``cumulative`` is True
    (cgType 30) - the stream, not the decoder, owns the differencing state.
    """
    kind: PinchKind
    value: float
    cumulative: bool = False


def decode_cg_event(etype: int, fields: dict) -> Optional[PinchEvent]:
    """Pure per-event decode: CGEvent type + {field number: value} in,
    PinchEvent out, None for anything that is not a pinch (wrong cgType,
    non-zoom subtype, missing value/phase fields, phase 0).

    Field keys are the INTEGER field numbers above - the same numbers the
    tap glue reads via CGEventGetIntegerValueField/…DoubleValueField and the
    fixtures carry (as JSON string keys, int-cast by the loader).
    """
    if etype == CG_TYPE_GESTURE:
        if fields.get(FIELD_SUBTYPE) != SUBTYPE_ZOOM:
            return None
        value = fields.get(FIELD_DELTA)
        cumulative = False
    elif etype == CG_TYPE_MAGNIFY:
        value = fields.get(FIELD_CUMULATIVE)
        cumulative = True
    else:
        return None
    phase = fields.get(FIELD_PHASE)
    if value is None or not phase:
        return None
    if phase == PHASE_BEGAN:
        kind = PinchKind.BEGIN
    elif phase == PHASE_CHANGED:
        kind = PinchKind.DELTA
    elif phase == PHASE_ENDED:
        kind = PinchKind.END
    else:
        kind = PinchKind.CANCEL
    return PinchEvent(kind=kind, value=float(value), cumulative=cumulative)


class PinchFactorStream:
    """Turns decoded PinchEvents into the coordinator's normalized callback
    stream: on_begin(), on_update(abs_factor) after every applied delta,
    on_end(cancelled) exactly once per gesture.

    Emission rules (fixture- and unit-pinned):

    - BEGIN (even while a gesture is open - a lost end): factor resets to
      1.0 and the cumulative baseline to 0.0, on_begin fires, then the
      Began event's own delta applies and publishes. The previous-gesture
      rebase policy lives in the coordinator/machine, never here.
    - DELTA: factor *= (1.0 + delta); cumulative events difference against
      the previous cumulative value first.
    - END: the final delta applies and publishes BEFORE on_end(False).
    - CANCEL: on_end(True) with the event's value DROPPED - an
      unknown-phase event's delta is unvetted evidence, so the factor
      freezes at the last known-good update.
    - Orphans (no open gesture) and feed(None) are silent no-ops (module
      docstring: begin-on-orphan would bypass the coordinator's begin gate).
    """

    def __init__(self, on_begin: Callable[[], None],
                 on_update: Callable[[float], None],
                 on_end: Callable[[bool], None]):
        self._on_begin = on_begin
        self._on_update = on_update
        self._on_end = on_end
        self._in_gesture = False
        self._factor = 1.0
        self._prev_cumulative = 0.0

    @property
    def in_gesture(self) -> bool:
        return self._in_gesture

    def feed(self, event: Optional[PinchEvent]) -> None:
        if event is None:
            return
        if event.kind is PinchKind.BEGIN:
            self._in_gesture = True
            self._factor = 1.0
            self._prev_cumulative = 0.0
            self._on_begin()
            self._apply(event)
            self._on_update(self._factor)
            return
        if not self._in_gesture:
            return   # orphan changed/end/cancel: dropped silently
        if event.kind is PinchKind.DELTA:
            self._apply(event)
            self._on_update(self._factor)
        elif event.kind is PinchKind.END:
            self._apply(event)
            self._on_update(self._factor)
            self._in_gesture = False
            self._on_end(False)
        else:   # CANCEL: terminate without applying the unvetted value
            self._in_gesture = False
            self._on_end(True)

    def _apply(self, event: PinchEvent) -> None:
        if event.cumulative:
            delta = event.value - self._prev_cumulative
            self._prev_cumulative = event.value
        else:
            delta = event.value
        self._factor *= (1.0 + delta)


class MacOSPinchTranslator:
    """Listen-only session CGEventTap that feeds decoded pinch events into the
    coordinator's on_begin / on_update(abs_factor) / on_end(cancelled)
    contract. This class is ONLY Quartz lifecycle glue - the pure decoder and
    PinchFactorStream above do every bit of interpretation.

    Coordinator contract (utils/overlay/pinch_zoom.py, see
    PinchZoomCoordinator.arm): the translator is ZERO-ARG constructible; the
    coordinator ASSIGNS on_begin / on_update / on_end as attributes AFTER
    construction and BEFORE start(); it then calls start(surfaces) and, on
    teardown, stop(). The armed stamp reads `mechanism`.

    Quartz is imported ONLY inside start() / stop() / the callback - the module
    top stays Qt- and Quartz-free (the suite's subprocess purity test pins
    this), so the pure decoder above imports on every platform.
    """

    # Read by the coordinator's armed stamp: "[PinchZoom] armed (cgtap) ...".
    mechanism = "cgtap"

    def __init__(self) -> None:
        # on_begin / on_update / on_end are NOT defined here: the coordinator
        # assigns them post-construction and the stream late-binds them at CALL
        # time (via the _emit_* wrappers). The Quartz surface + the per-session
        # stream are built in start().
        self._tap = None
        self._source = None
        self._callback = None       # bound-method ref, held alive for PyObjC
        self._quartz = None         # the imported module, used by the callback
        self._stream: Optional[PinchFactorStream] = None
        self._disable_traced = False
        self._callback_error_traced = False

    # ── lifecycle ────────────────────────────────────────────────────────

    def start(self, surfaces=()) -> None:
        """Create + enable the session-wide tap and hook it to the main
        CFRunLoop (Qt's cocoa integration pumps it; CP-P1 proved callbacks
        arrive in-process on that loop - no cross-thread marshaling).

        *surfaces* is accepted and IGNORED. The tap is SESSION-WIDE: it must
        see pinches while a game or Finder is frontmost (the inactive case
        CP-P1 relied on), so it cannot be scoped to our overlay windows. The
        coordinator's cursor_over_chrome begin-gate does ALL scoping; a
        per-surface tap would both miss the inactive case and duplicate that
        gate.

        Raises RuntimeError when the tap is denied (CGEventTapCreate returns
        None - no input-monitoring TCC grant / sandbox) so the coordinator
        disarms with that cause in the stamp, and when called twice without
        stop() (protocol misuse - the coordinator always stop()s first).
        """
        if self._tap is not None:
            raise RuntimeError("cgtap already started")
        # Deferred import: keeps the module (and the pure decoder above) Quartz-
        # free on non-macOS and under the purity test.
        import Quartz

        # Held so the callback reaches Quartz functions/constants without a
        # per-event re-import, and so PyObjC's ref to the callback outlives
        # this method.
        self._quartz = Quartz
        self._callback = self._on_tap_event
        # Fresh stream per session: a re-arm must never carry stale in-gesture
        # state. The _emit_* wrappers late-bind the coordinator-assigned
        # callbacks at CALL time.
        self._stream = PinchFactorStream(
            on_begin=self._emit_begin,
            on_update=self._emit_update,
            on_end=self._emit_end,
        )
        self._disable_traced = False
        self._callback_error_traced = False

        # Mask = gesture family (29) | dedicated magnify (30): the two cgTypes
        # the decoder speaks. Listen-only: we never mutate or drop events.
        mask = (1 << CG_TYPE_GESTURE) | (1 << CG_TYPE_MAGNIFY)
        tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionListenOnly,
            mask,
            self._callback,
            None,
        )
        if tap is None:
            # None == the OS refused the tap: no input-monitoring TCC grant (or
            # a sandbox). Reset the half-built refs so the object stays re-
            # armable, then surface the cause the coordinator's stamp names.
            self._quartz = None
            self._callback = None
            self._stream = None
            raise RuntimeError("cgtap denied - input monitoring permission?")
        source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
        Quartz.CFRunLoopAddSource(
            Quartz.CFRunLoopGetMain(), source, Quartz.kCFRunLoopCommonModes)
        Quartz.CGEventTapEnable(tap, True)
        self._tap = tap
        self._source = source

    def stop(self) -> None:
        """Disable the tap, unhook it from the run loop, and drop all refs.
        Safe when never started and safe to call twice (the coordinator's
        teardown / re-arm / disarm paths all call it). Refs are dropped BEFORE
        the Quartz teardown, so even a raising teardown leaves this object
        clean and idempotent; the coordinator guards the call anyway."""
        tap, self._tap = self._tap, None
        source, self._source = self._source, None
        quartz, self._quartz = self._quartz, None
        self._callback = None
        self._stream = None
        self._disable_traced = False
        self._callback_error_traced = False
        if quartz is None:
            return   # never started, or already stopped
        if tap is not None:
            quartz.CGEventTapEnable(tap, False)
        if source is not None:
            quartz.CFRunLoopRemoveSource(
                quartz.CFRunLoopGetMain(), source,
                quartz.kCFRunLoopCommonModes)

    # ── late-binding callback wrappers ───────────────────────────────────

    def _emit_begin(self) -> None:
        # Late binding: the coordinator assigns on_begin AFTER construction, so
        # resolve it at CALL time here rather than capturing it at start().
        self.on_begin()

    def _emit_update(self, factor: float) -> None:
        self.on_update(factor)

    def _emit_end(self, cancelled: bool) -> None:
        self.on_end(cancelled)

    # ── tap callback (runs on the main CFRunLoop) ────────────────────────

    def _on_tap_event(self, proxy, etype, event, refcon):
        """CGEventTap callback. Listen-only: it ALWAYS returns *event*
        unchanged (returning None or a substitute would drop/replace the
        user's real event). An exception escaping here would tear down event
        delivery for the whole session, so decode/stream faults are trapped -
        the coordinator's OWN callbacks carry the disarm-on-error policy; this
        trap only protects event delivery."""
        quartz = self._quartz
        if quartz is None:
            # A queued event landing after stop() (e.g. the coordinator
            # disarmed from inside a callback): nothing to do, and touching
            # the dropped refs would raise into the CFRunLoop.
            return event
        if etype in (quartz.kCGEventTapDisabledByTimeout,
                     quartz.kCGEventTapDisabledByUserInput):
            # The OS auto-disabled the tap (we starved the run loop past the
            # timeout, or user input forced it off). A listen-only tap can
            # always be re-enabled. Trace once per burst (leading edge only) so
            # a disable storm cannot flood the log; the flag clears when a real
            # event flows again.
            quartz.CGEventTapEnable(self._tap, True)
            reason = ("timeout"
                      if etype == quartz.kCGEventTapDisabledByTimeout
                      else "userinput")
            if not self._disable_traced:
                overlay_trace(f"[PinchZoom] cgtap re-enabled ({reason})")
                self._disable_traced = True
            return event
        self._disable_traced = False   # a real event flowed: the burst is over
        try:
            # Read ONLY the fields that exist per cgType (a missing double reads
            # 0.0, and d113==0.0 on a Changed event is a legal no-op delta - no
            # gating beyond the decoder's belongs here).
            if etype == CG_TYPE_GESTURE:
                # 29: subtype (110) + per-event delta (113) + phase (132).
                fields = {
                    FIELD_SUBTYPE: quartz.CGEventGetIntegerValueField(
                        event, FIELD_SUBTYPE),
                    FIELD_DELTA: quartz.CGEventGetDoubleValueField(
                        event, FIELD_DELTA),
                    FIELD_PHASE: quartz.CGEventGetIntegerValueField(
                        event, FIELD_PHASE),
                }
            elif etype == CG_TYPE_MAGNIFY:
                # 30: cumulative magnification (124) + phase (132). No subtype
                # gate (the decoder keys on cgType + d124).
                fields = {
                    FIELD_CUMULATIVE: quartz.CGEventGetDoubleValueField(
                        event, FIELD_CUMULATIVE),
                    FIELD_PHASE: quartz.CGEventGetIntegerValueField(
                        event, FIELD_PHASE),
                }
            else:
                return event   # outside the mask: unreachable, but defensive
            self._stream.feed(decode_cg_event(etype, fields))
        except Exception as exc:
            # A decode/callback bug must NEVER escape into the CFRunLoop. Keep
            # the tap alive; trace once so a persistent fault is visible without
            # spamming every event.
            if not self._callback_error_traced:
                overlay_trace(f"[PinchZoom] cgtap callback error ({exc})")
                self._callback_error_traced = True
        return event
