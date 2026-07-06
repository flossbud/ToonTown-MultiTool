"""Trackpad pinch-to-zoom for the Float UI overlay cluster.

Design: docs/superpowers/specs/2026-07-05-trackpad-pinch-zoom-design.md.
This module houses the pinch feature's platform-independent core: the pure
`PinchZoomStateMachine` below, plus (later) the Qt-thin coordinator that
wires a per-platform `GestureTranslator` to the cluster controller's
begin/update/end_scale_gesture API and owns the watchdog timer.

The MACHINE is deliberately PURE: no Qt, no timers, no I/O, no wall clock -
importable on any platform. Decisions are RETURN VALUES; the machine never
executes effects. The integration layer performs the actual transform
writes, input-shape transitions, and the single persist-on-termination.

Semantics (section 2.1 of the spec):

- `begin(base_scale)` enters ACTIVE from IDLE with base = the CURRENT
  RENDERED transform scale (never a tween target). `update(abs_factor)`
  tracks live = clamp_scale(base * abs_factor) - translators deliver the
  OS's absolute factor since gesture start, so each update replaces the
  last rather than compounding.
- `end()` is the ONLY terminator that snaps: it applies the same
  snap-to-1.0 window the wheel-notch path uses (scale.py SNAP_WINDOW).
  `cancel()` commits the current live scale with NO snap.
- Watchdog: the machine only publishes `PINCH_WATCHDOG_MS`; the integration
  layer owns the timer and calls `expire()` when ACTIVE goes quiet, which
  behaves exactly like `cancel()` (a lost gesture-end must never strand the
  broad input shape, and a forced termination must not snap).
- Malformed sequences are defined: `update`/`end`/`cancel` in IDLE are
  no-ops returning None. `begin` while ACTIVE (a lost end followed by a new
  physical gesture) commits the current live scale with cancel semantics,
  then re-begins with base = that committed live scale. Keeping the stale
  base would be wrong: a new gesture's factor stream restarts near 1.0, so
  stale-base math would snap the scale back and discard the first gesture's
  result.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

from utils.overlay.scale import SNAP_TARGET, SNAP_WINDOW, clamp_scale

# The machine does not track wall-clock time. The integration layer arms a
# timer with this deadline while ACTIVE and calls expire() when it fires.
PINCH_WATCHDOG_MS = 1500


class PinchState(Enum):
    IDLE = auto()    # no gesture in flight
    ACTIVE = auto()  # between begin and end/cancel/expire


@dataclass(frozen=True)
class Commit:
    """A termination decision: the scale the integration layer must commit.

    `snapped` is True only when end() pulled the value to SNAP_TARGET;
    cancel-semantics terminations always carry snapped=False.
    """
    scale: float
    snapped: bool


class PinchZoomStateMachine:
    """Pure IDLE/ACTIVE gesture-scale machine. Holds no Qt objects and no
    window state; every method returns a decision (or None) for the
    integration layer to execute."""

    def __init__(self) -> None:
        self._state = PinchState.IDLE
        self._base: Optional[float] = None
        self._live: Optional[float] = None

    # ── observers ────────────────────────────────────────────────────────

    @property
    def state(self) -> PinchState:
        return self._state

    @property
    def active(self) -> bool:
        return self._state is PinchState.ACTIVE

    @property
    def live_scale(self) -> Optional[float]:
        """Current live scale while ACTIVE, else None."""
        return self._live

    # ── transitions ──────────────────────────────────────────────────────

    def begin(self, base_scale: float) -> Optional[Commit]:
        """Start a gesture from the current rendered scale.

        IDLE -> ACTIVE, returns None. While ACTIVE (the previous gesture's
        end was lost), returns a Commit at the CURRENT live scale with
        cancel semantics (no snap) and re-begins with base = that committed
        live scale: the new gesture's factor stream restarts near 1.0, so a
        stale base would snap the scale back and discard the first
        gesture's result.
        """
        if self._state is PinchState.ACTIVE:
            commit = Commit(scale=self._live, snapped=False)
            self._base = self._live  # rebase on what was just committed
            return commit
        self._state = PinchState.ACTIVE
        self._base = float(base_scale)
        self._live = self._base
        return None

    def update(self, abs_factor: float) -> Optional[float]:
        """Track the OS's absolute factor since gesture start.

        Returns the new clamped live scale, or None when IDLE (defined
        no-op) or when the factor is non-positive (malformed input,
        ignored).
        """
        if self._state is not PinchState.ACTIVE:
            return None
        if abs_factor <= 0:
            return None
        self._live = clamp_scale(self._base * abs_factor)
        return self._live

    def end(self) -> Optional[Commit]:
        """Normal gesture end: the only terminator that snaps.

        ACTIVE -> IDLE, returns Commit(final, snapped) where final applies
        the wheel-notch path's snap-to-1.0 window. IDLE -> None.
        """
        if self._state is not PinchState.ACTIVE:
            return None
        final = self._live
        snapped = abs(final - SNAP_TARGET) < SNAP_WINDOW + 1e-9
        if snapped:
            final = SNAP_TARGET
        self._reset()
        return Commit(scale=final, snapped=snapped)

    def cancel(self) -> Optional[Commit]:
        """OS-cancelled gesture: commit the current live scale, NO snap.

        ACTIVE -> IDLE, returns Commit(live, snapped=False). IDLE -> None.
        """
        if self._state is not PinchState.ACTIVE:
            return None
        commit = Commit(scale=self._live, snapped=False)
        self._reset()
        return commit

    # Watchdog expiry IS a cancel: one termination behavior, no drift.
    expire = cancel

    def _reset(self) -> None:
        self._state = PinchState.IDLE
        self._base = None
        self._live = None
