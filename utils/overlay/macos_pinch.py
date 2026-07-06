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
