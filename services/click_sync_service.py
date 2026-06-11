"""Click sync: mirror left-button gestures between same-aspect TTR windows.

Observe-only capture (XRecord), per-gesture geometry snapshot, XSendEvent
injection. Spec: docs/superpowers/specs/2026-06-10-click-sync-design.md.

Threading: capture events arrive on the XRecord thread; UI calls arrive on
the GUI thread. ALL state mutation goes through self._lock (an RLock). Qt
signals are emitted via _emit_if_current, whose generation check and emit
are atomic under the lock (see its docstring for why that is safe); capture
start()/stop() always run with the lock released.
"""
from __future__ import annotations

import os
import threading
from time import monotonic

from PySide6.QtCore import QObject, Signal

from services.click_sync_logic import (
    Gesture, aspect_compatible, compute_slot_states, map_point, SLOT_COUNT,
)

MOTION_COALESCE_S = 0.016  # forward at most ~60 motion events/s per gesture
BUTTON1_MASK = 0x100  # X.Button1Mask; drains force it set on the release


def _trace_enabled() -> bool:
    return bool(os.environ.get("TTMT_INPUT_TRACE"))


def _trace(msg: str) -> None:
    if _trace_enabled():
        print(f"[click] {msg}", flush=True)


class ClickSyncService(QObject):
    # {slot(int): "off"|"armed"|"active"|"error"}; emitted on every state
    # change. Signal(object), NOT Signal(dict): PySide6 marshals dict
    # parameters through QVariantMap, which cannot represent int keys and
    # delivers an EMPTY dict to slots (verified live). object passes the
    # Python dict through untouched.
    slot_states_changed = Signal(object)
    # Emitted once if the capture backend dies / cannot start.
    service_error = Signal(str)

    def __init__(self, slot_window_resolver, geometry_provider,
                 source_resolver, backend, capture_factory, parent=None,
                 fresh_geometry_provider=None):
        """slot_window_resolver(slot:int) -> wid|None
        geometry_provider(wid:str) -> (x, y, w, h)|None  (cached is fine:
            drives the periodic aspect-compatibility re-check)
        fresh_geometry_provider(wid) -> same, but must be a LIVE query:
            gesture snapshots are taken from it at press time, where a ~2s
            stale origin would mismap the injection (a window moved then
            clicked immediately). Defaults to geometry_provider.
        source_resolver(root_x, root_y, member_wids:list) -> wid|None
            (stacking-aware hit test; see wire-up in Task 9)
        backend: object with send_button_press/send_button_release/send_motion
        capture_factory(on_event) -> object with start()/stop()/is_running()
        """
        super().__init__(parent)
        self._slot_window_resolver = slot_window_resolver
        self._geometry_provider = geometry_provider
        self._fresh_geometry_provider = (fresh_geometry_provider
                                         or geometry_provider)
        self._source_resolver = source_resolver
        self._backend = backend
        self._capture_factory = capture_factory

        self._lock = threading.RLock()
        self._enabled = False
        self._members: set[int] = set()
        self._gesture: Gesture | None = None
        self._capture = None
        self._states = {s: "off" for s in range(SLOT_COUNT)}
        self._last_motion_emit = 0.0
        self._pending_motion = None  # (root_x, root_y, state, time)
        self._shutdown = False
        # Sticky service-level failure latch (capture died / start failed).
        # Prevents the periodic recompute from auto-restarting a broken
        # capture and re-emitting service_error every tick; cleared only by
        # an explicit user action (master toggle or membership change).
        self._service_failed = False
        # Bumped on every _states mutation; slow-path emitters snapshot it
        # and drop superseded emissions (_emit_if_current).
        self._states_gen = 0

    # ── public API (GUI thread) ────────────────────────────────────────

    def set_enabled(self, enabled: bool) -> None:
        """Master switch. Disabling drains + pauses but RETAINS membership
        (spec: OFF -> ON in the same session restores the group)."""
        with self._lock:
            if self._enabled == bool(enabled):
                return
            self._enabled = bool(enabled)
            self._service_failed = False  # user action clears the latch
            if not self._enabled:
                self._drain_locked("master disabled")
        self.recompute()

    def toggle_slot(self, slot: int) -> bool:
        """Flip group membership for a toon slot. Returns new membership."""
        with self._lock:
            self._service_failed = False  # user action clears the latch
            if slot in self._members:
                self._members.discard(slot)
                if self._gesture is not None:
                    self._drain_locked(f"slot {slot} left group")
                member = False
            else:
                self._members.add(slot)
                member = True
        self.recompute()
        return member

    def slot_states(self) -> dict[int, str]:
        with self._lock:
            return dict(self._states)

    def recompute(self) -> None:
        """Re-evaluate usability + aspect compatibility and (re)start or stop
        capture. Called on toggles, the master switch, window-list updates,
        and the periodic geometry tick.

        Capture lifecycle changes are DECIDED under the lock but EXECUTED
        outside it: start() opens X connections (multiple round trips) and
        stop() joins a thread whose callback takes this same lock. A new
        capture is published under the lock only if the service still wants
        it (a concurrent recompute/disable may have won the race; the loser
        is stopped)."""
        emit_states = None
        to_stop = None
        start_new = False
        with self._lock:
            if self._shutdown:
                return
            if not self._enabled:
                new_states = {s: "off" for s in range(SLOT_COUNT)}
            elif self._service_failed:
                # Sticky error: hold the error display, no auto-restart.
                new_states = {
                    s: ("error" if s in self._members else "off")
                    for s in range(SLOT_COUNT)
                }
            else:
                usable, geoms = {}, []
                for s in self._members:
                    wid = self._slot_window_resolver(s)
                    g = self._geometry_provider(wid) if wid else None
                    usable[s] = g is not None
                    if g is not None:
                        geoms.append(g)
                compatible = aspect_compatible(geoms)
                new_states = compute_slot_states(self._members, usable, compatible)
            was_active = "active" in self._states.values()
            now_active = "active" in new_states.values()
            if was_active and not now_active and self._gesture is not None:
                self._drain_locked("group paused")
            if new_states != self._states:
                self._set_states_locked(new_states)
                emit_states = dict(new_states)
            emit_error = False
            if now_active:
                cap = self._capture
                if cap is None:
                    start_new = True
                elif not cap.is_running():
                    # The capture died but its on_died notification hasn't
                    # been processed yet. Treat it as the death HERE (latch,
                    # reclaim, error) — never silently restart a new
                    # generation ahead of the death notification; the late
                    # on_died then identity-misses and is a no-op.
                    to_stop, self._capture = cap, None
                    self._service_failed = True
                    self._drain_locked("capture dead at recompute")
                    self._set_states_locked({
                        s: ("error" if s in self._members else "off")
                        for s in range(SLOT_COUNT)
                    })
                    emit_states = dict(self._states)
                    emit_error = True
            else:
                to_stop, self._capture = self._capture, None
            emit_gen = self._states_gen
        # Outside the lock from here. Emit BEFORE stop(): stop can block on
        # a thread join and must not delay the UI state flip.
        if emit_states is not None:
            self._emit_if_current(
                emit_states, emit_gen,
                error_msg=("mouse capture stopped unexpectedly"
                           if emit_error else None),
                trace_msg=("service error: capture dead at recompute"
                           if emit_error else None))
        if to_stop is not None:
            to_stop.stop()
        if start_new:
            self._start_capture_outside_lock()

    def _set_states_locked(self, new_states) -> None:
        """All _states mutations go through here (lock held): the generation
        bump lets slow-path emitters detect superseded snapshots."""
        self._states = new_states
        self._states_gen += 1

    def _emit_if_current(self, states, gen, error_msg=None, trace_msg=None):
        """Emit a state snapshot only if no newer state change superseded it
        (a slow path's stale emission must not land after, say, a user
        recovery already flipped the buttons back). The check AND the emit
        happen under the lock — atomically — which is safe because the lock
        is an RLock (a same-thread direct-connected slot reenters fine) and
        cross-thread consumers get queued delivery (their slots never run
        under this lock)."""
        with self._lock:
            if gen != self._states_gen:
                return
            if trace_msg:
                _trace(trace_msg)
            self.slot_states_changed.emit(states)
            # A same-thread direct slot may have reentered (RLock) during
            # the emit and recovered the state; recheck before pairing the
            # error message with a generation that no longer exists.
            if error_msg is not None and gen == self._states_gen:
                self.service_error.emit(error_msg)

    def _make_capture_callback(self):
        """Generation-gated event callback: a capture that lost the publish
        race (or was replaced) may still deliver events from its stream;
        only the CURRENTLY PUBLISHED generation's events may inject. The
        generation check and the event handling share ONE lock acquisition
        (a gate-then-call split would let a detachment land in between)."""
        holder = []

        def cb(kind, root_x, root_y, state, time):
            with self._lock:
                if not holder or self._capture is not holder[0]:
                    return
                self._handle_event_locked(kind, root_x, root_y, state, time)

        return cb, holder

    def _start_capture_outside_lock(self) -> None:
        """Build and start a capture with no locks held, then publish it
        under the lock — or stop it if the service no longer wants it.
        Publication verifies is_running(): an instant-death capture (start
        succeeded, thread died before publication) is treated as a start
        FAILURE and stopped by this starter — that completes the stop-
        ownership map (every detach site owns its instance), which is what
        lets notify_capture_died's stale branch be a no-op."""
        cb, holder = self._make_capture_callback()
        new_cap = self._capture_factory(cb)
        holder.append(new_cap)
        ok = new_cap.start() and new_cap.is_running()
        fail_states = None
        fail_gen = 0
        publish = False
        with self._lock:
            wanted = (not self._shutdown
                      and "active" in self._states.values()
                      and self._capture is None)
            if ok and wanted:
                self._capture = new_cap
                publish = True
            elif not ok and wanted:
                self._service_failed = True
                self._set_states_locked({
                    s: ("error" if s in self._members else "off")
                    for s in range(SLOT_COUNT)
                })
                fail_states = dict(self._states)
                fail_gen = self._states_gen
        if not publish:
            new_cap.stop()  # idempotent; reclaims connections on failure too
        if fail_states is not None:
            self._emit_if_current(
                fail_states, fail_gen,
                error_msg="mouse capture unavailable",
                trace_msg="service error: mouse capture unavailable")

    def shutdown(self) -> None:
        """Idempotent: drain, stop capture, refuse further work."""
        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
            self._drain_locked("shutdown")
            cap, self._capture = self._capture, None
        if cap is not None:
            cap.stop()

    def notify_capture_died(self, cap=None) -> None:
        """Hooked to XRecordCapture's on_died: a capture thread died
        unexpectedly. `cap` identifies the dying generation: if it is a
        STALE instance (recompute already replaced it), only its X
        connections are reclaimed — the current healthy capture and the
        states stay untouched. Otherwise: stop the capture (NEVER just drop
        the reference — the dead capture still holds two X connections and
        dropping it leaks client slots; stop() is safe from the capture
        thread itself), drain, latch the failure, and drop to a
        service-level error state (member buttons show error; keyboard
        routing unaffected; no auto-restart until a user action)."""
        states = None
        gen = 0
        with self._lock:
            if self._shutdown:
                return
            current = self._capture
            if cap is not None and cap is not current:
                # Stale/detached generation. Every detach site owns stopping
                # its instance (recompute's death/deactivation branches, the
                # publish-or-lose / instant-death starter, the full death
                # path below), so there is nothing to stop here — and a
                # second stop() would contend with the owner's across locks.
                _trace("stale capture death ignored (owner stops it)")
                return
            to_stop = current if current is not None else cap
            self._capture = None
            self._service_failed = True
            self._drain_locked("capture died")
            self._set_states_locked({
                s: ("error" if s in self._members else "off")
                for s in range(SLOT_COUNT)
            })
            states = dict(self._states)
            gen = self._states_gen
        # Emit BEFORE the (potentially slow, thread-joining) stop().
        if states is not None:
            self._emit_if_current(
                states, gen,
                error_msg="mouse capture stopped unexpectedly",
                trace_msg="service error: capture died")
        if to_stop is not None:
            to_stop.stop()

    # ── capture events (XRecord thread) ────────────────────────────────

    def _on_capture_event(self, kind: str, root_x: int, root_y: int,
                          state: int, time: int) -> None:
        with self._lock:
            self._handle_event_locked(kind, root_x, root_y, state, time)

    def _handle_event_locked(self, kind: str, root_x: int, root_y: int,
                             state: int, time: int) -> None:
        if self._shutdown or not self._enabled:
            return
        if kind == "press":
            self._handle_press_locked(root_x, root_y, state, time)
        elif kind == "motion":
            self._handle_motion_locked(root_x, root_y, state, time)
        elif kind == "release":
            self._handle_release_locked(root_x, root_y, state, time)

    def _member_wids_locked(self) -> dict[int, str]:
        out = {}
        for s in self._members:
            wid = self._slot_window_resolver(s)
            if wid:
                out[s] = wid
        return out

    def _handle_press_locked(self, root_x, root_y, state, time):
        if "active" not in self._states.values() or self._gesture is not None:
            return
        wids_by_slot = self._member_wids_locked()
        src_wid = self._source_resolver(root_x, root_y, list(wids_by_slot.values()))
        if src_wid is None:
            return
        src_slot = next(s for s, w in wids_by_slot.items() if w == src_wid)
        # Gesture snapshots come from the FRESH provider: the cached
        # geometry can be ~2s old, and a window moved-then-clicked would
        # mismap every injection for the whole gesture. Presses are rare,
        # so the extra X round trips are cheap.
        src_geom = self._fresh_geometry_provider(src_wid)
        if src_geom is None or src_geom[2] <= 0 or src_geom[3] <= 0:
            return
        targets = {}
        for s, wid in wids_by_slot.items():
            # Skip the source slot AND any slot that resolved to the same
            # window id (a duplicate mapping must never echo a synthetic
            # press back into the source window).
            if s == src_slot or wid == src_wid:
                continue
            g = self._fresh_geometry_provider(wid)
            if g is None or g[2] <= 0 or g[3] <= 0:
                continue  # zero-size = mid-teardown window; never inject
            tx, ty = map_point(src_geom, g, root_x, root_y)
            targets[s] = (wid, g, (tx, ty))
        if not targets:
            return
        _trace(f"press src=slot{src_slot} rel=({(root_x - src_geom[0]) / src_geom[2]:.3f},"
               f"{(root_y - src_geom[1]) / src_geom[3]:.3f}) -> {len(targets)} targets")
        delivered = {}
        for slot, (wid, g, (tx, ty)) in targets.items():
            ok = self._backend.send_button_press(
                wid, tx, ty, g[0] + tx, g[1] + ty, state=state, time=time)
            if ok:
                delivered[slot] = (wid, g, (tx, ty))
            else:
                # Spec: backend failure (BadWindow) drops that target from
                # the gesture; WindowManager re-detection restores the slot.
                _trace(f"press inject failed slot{slot} wid={wid}; target dropped")
        if not delivered:
            return
        self._gesture = Gesture(
            source_slot=src_slot, source_geom=src_geom,
            press_root=(root_x, root_y), press_state=state,
            press_time=time, targets=delivered)
        self._last_motion_emit = 0.0
        self._pending_motion = None

    def _handle_motion_locked(self, root_x, root_y, state, time):
        if self._gesture is None:
            return
        now = monotonic()
        if now - self._last_motion_emit >= MOTION_COALESCE_S:
            self._emit_motion_locked(root_x, root_y, state, time)
            self._last_motion_emit = now
            self._pending_motion = None
        else:
            self._pending_motion = (root_x, root_y, state, time)

    def _emit_motion_locked(self, root_x, root_y, state, time):
        g = self._gesture
        for wid, geom, _ in g.targets.values():
            tx, ty = map_point(g.source_geom, geom, root_x, root_y)
            # Return value intentionally ignored (spec deviation, recorded
            # there): a target dying mid-gesture is reclaimed by window
            # re-detection and the next geometry tick within ~2s.
            self._backend.send_motion(
                wid, tx, ty, geom[0] + tx, geom[1] + ty, state=state, time=time)

    def _handle_release_locked(self, root_x, root_y, state, time):
        if self._gesture is None:
            return
        if self._pending_motion is not None:
            self._emit_motion_locked(*self._pending_motion)
            self._pending_motion = None
        g, self._gesture = self._gesture, None
        _trace(f"release -> {len(g.targets)} targets")
        for wid, geom, _ in g.targets.values():
            tx, ty = map_point(g.source_geom, geom, root_x, root_y)
            self._backend.send_button_release(
                wid, tx, ty, geom[0] + tx, geom[1] + ty, state=state, time=time)

    # ── drain (call with lock held) ────────────────────────────────────

    def _drain_locked(self, reason: str):
        if self._gesture is None:
            return
        g, self._gesture = self._gesture, None
        self._pending_motion = None
        _trace(f"drain ({reason}) -> {len(g.targets)} targets")
        for wid, geom, (tx, ty) in g.targets.values():
            # Spec: drain at the gesture's mapped press coordinates,
            # state = press state with Button1Mask set, press timestamp.
            self._backend.send_button_release(
                wid, tx, ty, geom[0] + tx, geom[1] + ty,
                state=g.press_state | BUTTON1_MASK, time=g.press_time)
