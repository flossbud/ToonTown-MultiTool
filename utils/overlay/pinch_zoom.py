"""Trackpad pinch-to-zoom for the Float UI overlay cluster.

Design: docs/superpowers/specs/2026-07-05-trackpad-pinch-zoom-design.md.
This module houses the pinch feature's platform-independent core: the pure
`PinchZoomStateMachine` below, plus the Qt-thin `PinchZoomCoordinator` that
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

import os
import sys
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

# Qt-free by design (backend.py is os/sys only): the pure machine and the
# module itself stay importable with zero Qt - every PySide6 import in the
# coordinator is deferred to call time (pinned by the machine suite's
# subprocess purity test).
from utils.overlay.backend import overlay_trace
from utils.overlay.scale import SNAP_TARGET, SNAP_WINDOW, clamp_scale

# The machine does not track wall-clock time. The integration layer arms a
# timer with this deadline while ACTIVE and calls expire() when it fires.
PINCH_WATCHDOG_MS = 1500

# GestureTranslator registry, keyed by platform bucket (`platform_bucket()`).
# Values are zero-arg factories returning a started-later translator: the
# coordinator assigns the three callback attributes (on_begin / on_update /
# on_end), then calls start(surfaces) / stop(). SHIPS EMPTY in Phase 1 -
# translators are probe-gated follow-on plans (spec section 3) - so every
# platform arms to "[PinchZoom] unavailable (no translator: <bucket>)" until
# its translator lands and registers here.
TRANSLATOR_REGISTRY: dict = {}


def platform_bucket() -> str:
    """Registry key for translator selection: one bucket per OS input stack
    ("darwin" / "win32" / "linux" - every linux* spelling collapses to the
    X11 bucket). Selection is STATIC per bucket (spec 2.2): no runtime
    fallback between mechanisms."""
    if sys.platform.startswith("linux"):
        return "linux"
    return sys.platform


def _pinch_disabled() -> bool:
    """TTMT_NO_PINCH_ZOOM kill switch, parsed like the other overlay
    switches (any truthy spelling disables). Read at arm time AND at every
    gesture begin, so flipping it mid-session needs no restart to take
    effect on the next gesture."""
    return os.environ.get("TTMT_NO_PINCH_ZOOM", "").strip().lower() \
        not in ("", "0", "no", "n", "false", "f", "off")


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


class PinchZoomCoordinator:
    """Qt-thin integration layer: one QTimer, env reads, and trace stamps -
    no native calls (those live in the translators, follow-on plans).

    Owns the policy the pure machine and the dumb translators must not:

    - The begin gate (spec 2.4): kill switch unset, controller active, no
      cluster drag in progress, cursor over float chrome
      (`controller.cursor_over_chrome`). A blocked begin leaves the machine
      IDLE. Once ACTIVE, updates flow even after the cursor drifts off
      chrome - only end/cancel/watchdog/force-cancel terminate.
    - The watchdog: (re)started on every translator event while ACTIVE;
      expiry terminates with cancel semantics (commit current, NO snap), so
      a lost gesture-end can never strand the controller's BROAD input
      shape.
    - Arming (spec 2.6): translator selection from the platform-bucket
      registry, with exactly one stamp per arm attempt
      (disabled / unavailable / armed / disarmed) - the running-code proof
      live validation starts from.
    - Disarm-on-error (spec 2.2): any exception out of the translator path
      (start() or mid-callback) terminates the gesture through the single
      termination path, stops the translator, stamps
      "[PinchZoom] disarmed (<error>)", and never propagates.

    Every termination funnels through `controller.end_scale_gesture` (the
    public face of the controller's single termination path); the machine's
    return-value decisions are the only scale math consumed here.

    Lifecycle: constructed once at the controller's emblem wiring site,
    armed per float session (enter), stopped at leave - the coordinator
    outlives float sessions, its translator does not.
    """

    def __init__(self, controller, *, cursor_pos=None,
                 watchdog_ms: int = PINCH_WATCHDOG_MS, registry=None):
        self._controller = controller
        # Injectable cursor supplier (tests); None -> QCursor.pos at call
        # time (deferred: this module must import Qt-free).
        self._cursor_pos = cursor_pos
        self._watchdog_ms = int(watchdog_ms)
        self._registry = registry if registry is not None \
            else TRANSLATOR_REGISTRY
        self._machine = PinchZoomStateMachine()
        self._translator = None
        self._watchdog = None   # lazy single-shot QTimer
        self._armed = False

    @property
    def armed(self) -> bool:
        return self._armed

    # ── arming / teardown ────────────────────────────────────────────────

    def arm(self, surfaces=()) -> bool:
        """One arm attempt: stop any previous arming, then select and start
        the platform translator. Exactly ONE stamp per call - disabled /
        unavailable / armed / disarmed are always distinguishable from the
        trace alone. *surfaces* are the overlay windows the translator
        watches (cluster, radial, panel). Returns True only when armed."""
        self.stop()   # re-arm safe; stop() stamps nothing
        if _pinch_disabled():
            overlay_trace("[PinchZoom] disabled (env)")
            return False
        bucket = platform_bucket()
        factory = self._registry.get(bucket)
        if factory is None:
            overlay_trace(f"[PinchZoom] unavailable (no translator: {bucket})")
            return False
        try:
            translator = factory()
            self._translator = translator
            translator.on_begin = self.on_begin
            translator.on_update = self.on_update
            translator.on_end = self.on_end
            translator.start(tuple(surfaces))
        except Exception as exc:
            self._disarm(exc)
            return False
        self._armed = True
        from PySide6.QtCore import qVersion
        mechanism = getattr(translator, "mechanism", "unknown")
        overlay_trace(f"[PinchZoom] armed ({mechanism}) "
                      f"qt={qVersion()} platform={bucket}")
        return True

    def stop(self) -> None:
        """Full teardown (leave(), re-arm, disarm): terminate any live
        gesture with cancel semantics, stop the watchdog, stop + drop the
        translator. Idempotent and total - a raising translator stop cannot
        leave the gesture live or the broad shape held (the gesture is
        already terminated by then)."""
        try:
            self.force_cancel()
        except Exception:
            pass
        translator, self._translator = self._translator, None
        self._armed = False
        if translator is not None:
            try:
                translator.stop()
            except Exception:
                pass

    def force_cancel(self) -> None:
        """Terminate any live gesture with cancel semantics (commit the
        current live scale, NO snap) through the controller's single
        termination path. The drag-start interlock and leave() run this
        BEFORE their own work. No-op while IDLE."""
        self._stop_watchdog()
        commit = self._machine.cancel()
        if commit is not None:
            self._controller.end_scale_gesture(commit.scale)

    def _disarm(self, error) -> None:
        """Translator failure: release everything (gesture terminated ->
        broad shape released, watchdog stopped, translator stopped), then
        stamp. Pinch stays disarmed for the session; the next arm attempt
        (next float enter) may try again."""
        self.stop()
        overlay_trace(f"[PinchZoom] disarmed ({error})")

    # ── translator-facing callbacks (never raise into the event pump) ────

    def on_begin(self) -> None:
        try:
            self._handle_begin()
        except Exception as exc:
            self._disarm(exc)

    def on_update(self, abs_factor: float) -> None:
        try:
            if not self._machine.active:
                return   # stray update after end/force-cancel: defined no-op
            live = self._machine.update(abs_factor)
            if live is not None:
                self._controller.update_scale_gesture(live)
            self._restart_watchdog()
        except Exception as exc:
            self._disarm(exc)

    def on_end(self, cancelled: bool) -> None:
        try:
            self._stop_watchdog()
            commit = self._machine.cancel() if cancelled \
                else self._machine.end()
            if commit is not None:
                self._controller.end_scale_gesture(commit.scale)
        except Exception as exc:
            self._disarm(exc)

    def _handle_begin(self) -> None:
        ctrl = self._controller
        if self._machine.active:
            # Lost gesture-end + a new physical gesture (machine 2.1
            # semantics): commit the current live scale with cancel
            # semantics through the single termination path, then re-open
            # rebased at the committed scale. The begin gate is NOT re-run -
            # the machine defines this transition unconditionally, and the
            # watchdog still bounds a pathological stream.
            commit = self._machine.begin(self._machine.live_scale)
            if commit is not None:
                ctrl.end_scale_gesture(commit.scale)
            if ctrl.begin_scale_gesture() is None:
                # The controller refused the re-open (left float mid-
                # stream): drop the machine to IDLE rather than strand it.
                self._machine.cancel()
                self._stop_watchdog()
                return
            self._restart_watchdog()
            return
        # The begin gate (spec 2.4). Deliberately NO app-active test: the
        # overlay is nonactivating by design.
        if _pinch_disabled():
            return
        if not bool(getattr(ctrl, "is_active", False)):
            return
        if bool(getattr(ctrl, "drag_in_progress", False)):
            return
        pos = self._cursor_point()
        if pos is None or not ctrl.cursor_over_chrome(pos):
            return
        base = ctrl.begin_scale_gesture()
        if base is None:
            return   # controller refused (raced a raw-API gesture)
        self._machine.begin(base)
        self._restart_watchdog()

    def _cursor_point(self):
        if self._cursor_pos is not None:
            return self._cursor_pos()
        from PySide6.QtGui import QCursor
        return QCursor.pos()

    # ── watchdog ─────────────────────────────────────────────────────────

    def _restart_watchdog(self) -> None:
        # QTimer.start() on a running timer restarts it: one call site for
        # both the initial arm and the per-event re-arm.
        if self._watchdog is None:
            from PySide6.QtCore import QTimer
            timer = QTimer()
            timer.setSingleShot(True)
            timer.setInterval(self._watchdog_ms)
            timer.timeout.connect(self._on_watchdog_expired)
            self._watchdog = timer
        self._watchdog.start()

    def _stop_watchdog(self) -> None:
        if self._watchdog is not None:
            self._watchdog.stop()

    def _on_watchdog_expired(self) -> None:
        # Expiry IS a cancel (commit current, no snap): a lost gesture-end
        # must never strand the broad input shape, and a forced termination
        # must not snap. Guarded like the callbacks - a timer slot exception
        # would otherwise escape into the Qt event loop.
        try:
            commit = self._machine.expire()
            if commit is not None:
                self._controller.end_scale_gesture(commit.scale)
        except Exception as exc:
            self._disarm(exc)
