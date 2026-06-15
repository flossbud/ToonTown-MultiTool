"""Click sync: mirror left-button gestures between same-aspect TTR windows.

Observe-only capture (XRecord), per-gesture geometry snapshot, XSendEvent
injection. Spec: docs/superpowers/specs/2026-06-10-click-sync-design.md.

Threading: capture events arrive on the XRecord thread; UI calls arrive on
the GUI thread. ALL state mutation goes through self._lock (an RLock). Qt
signals are emitted via _emit_if_current, whose generation check and emit
are atomic under the lock (see its docstring for why that is safe); the ghost
signals are an event stream, not a state snapshot, so they are emitted directly
under the lock and rely on queued delivery for cross-thread consumers. Capture
start()/stop() always runs with the lock released.
"""
from __future__ import annotations

import os
import threading
from time import monotonic

from PySide6.QtCore import QObject, Signal

from services.click_sync_logic import (
    Gesture, aspect_compatible, compute_slot_states, map_point,
    rect_hit_test, SLOT_COUNT,
)

MOTION_COALESCE_S = 0.016  # forward at most ~60 motion events/s per gesture
HOVER_CONFIRM_S = 0.25  # re-run the authoritative hit test at most this often
BUTTON1_MASK = 0x100  # X.Button1Mask; drains force it set on the release
HELD_BUTTONS_MASK = 0x1F00  # Button1Mask..Button5Mask: any held pointer button


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
    # Ghost cursors: one batched sample per forwarded event. Payload is
    # (kind, [(slot, screen_x, screen_y), ...]) with kind in
    # "motion" | "press" | "release". Coordinates are NATIVE root-space
    # pixels (the OS units capture/geometry/injection run in); the
    # renderer converts to Qt logical coordinates before positioning
    # (_ghost_cursors._native_to_logical — the spaces differ whenever a
    # screen's devicePixelRatio is not 1).
    # Signal(object) for the same marshaling reason as slot_states_changed.
    ghost_pointer_event = Signal(object)
    # All ghosts hide instantly: emitted from _clear_hover_locked, which
    # runs at every stop moment (master off, membership change, group
    # pause, capture death, shutdown).
    ghost_clear = Signal()

    def __init__(self, slot_window_resolver, geometry_provider,
                 source_resolver, backend, capture_factory, parent=None,
                 fresh_geometry_provider=None, delivery_ready=None):
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
        # Optional (ready: bool, reason: str|None) probe consulted before going
        # active and on every recompute tick. Default = always-ready so Linux/
        # Windows are unchanged; darwin passes backend.mouse_delivery_ready.
        self._delivery_ready_fn = delivery_ready or (lambda: (True, None))

        self._lock = threading.RLock()
        self._enabled = False
        self._members: set[int] = set()
        self._gesture: Gesture | None = None
        self._capture = None
        self._states = {s: "off" for s in range(SLOT_COUNT)}
        self._last_motion_emit = 0.0
        self._pending_motion = None  # (root_x, root_y, state, time)
        # Hover forwarding (unclicked motion; spec
        # 2026-06-10-hover-motion-forwarding-design.md). Separate from the
        # gesture coalescer: the two paths are mutually exclusive but must not
        # bleed state through a press.
        self._hover_source = None        # (slot, wid) latched confirmed source
        self._hover_rejected = None      # (slot, wid) last confirm-rejected candidate
        self._hover_last_confirm = 0.0
        self._hover_last_emit = 0.0
        self._hover_pending = None       # (root_x, root_y, state, time)
        self._hover_flush_timer = None   # threading.Timer (trailing flush)
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
                self._clear_hover_locked()
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
            self._clear_hover_locked()
        self.recompute()
        return member

    def slot_states(self) -> dict[int, str]:
        with self._lock:
            return dict(self._states)

    def _delivery_ready(self):
        """(ready, reason). FAIL-CLOSED: a probe exception returns NOT-ready. Mouse
        delivery rides a private-ABI path, so an unverifiable state must NOT be treated
        as working (contrast has_post_access, which fails open for keyboard)."""
        try:
            ready, reason = self._delivery_ready_fn()
            return (bool(ready), reason)
        except Exception as e:
            return (False, f"delivery-readiness probe error: {type(e).__name__}")

    def _fail_delivery_locked(self, reason):
        """Stop the capture, drain any in-flight gesture, and put members into the
        error state with `reason`. Caller holds self._lock. Returns the capture to stop
        (the caller stops it OUTSIDE the lock, like the recompute path). Idempotent."""
        to_stop, self._capture = self._capture, None
        self._service_failed = True
        if self._gesture is not None:
            self._drain_locked(reason)
        self._clear_hover_locked()
        self._set_states_locked({
            s: ("error" if s in self._members else "off") for s in range(SLOT_COUNT)
        })
        return to_stop

    def recompute(self) -> None:
        """Re-evaluate usability + aspect compatibility and (re)start or stop
        capture. Called on toggles, the master switch, window-list updates,
        and the periodic geometry tick.

        Members whose slot no longer resolves to a window are EVICTED here
        (final — no auto-rejoin; spec
        2026-06-12-click-sync-evict-windowless-design.md). Geometry-lookup
        failures on a live window do NOT evict: they pause the group via
        the error state and auto-recover.

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
                # Evict members whose slot no longer has a window (the game
                # window was closed). Eviction is FINAL: a relaunched toon
                # needs a re-click (spec
                # 2026-06-12-click-sync-evict-windowless-design.md). A
                # member whose window EXISTS but fails geometry lookup is
                # NOT evicted — that is a transient pause (error state),
                # not an assignment loss.
                wids = {s: self._slot_window_resolver(s) for s in self._members}
                evicted = {s for s, wid in wids.items() if wid is None}
                if evicted:
                    self._members -= evicted
                    if self._gesture is not None:
                        self._drain_locked("member window lost")
                    self._clear_hover_locked()
                usable, geoms = {}, []
                for s in self._members:
                    g = self._geometry_provider(wids[s])
                    usable[s] = g is not None
                    if g is not None:
                        geoms.append(g)
                compatible = aspect_compatible(geoms)
                new_states = compute_slot_states(self._members, usable, compatible)
            was_active = "active" in self._states.values()
            now_active = "active" in new_states.values()
            if was_active and not now_active:
                if self._gesture is not None:
                    self._drain_locked("group paused")
                self._clear_hover_locked()
            if new_states != self._states:
                self._set_states_locked(new_states)
                emit_states = dict(new_states)
            emit_error = False
            err_reason = None
            dr_ok, dr_reason = self._delivery_ready() if now_active else (True, None)
            if now_active and not dr_ok:
                # Delivery unavailable (missing SkyLight symbols / revoked access /
                # a sticky engine fault): refuse/stop the capture and latch the error
                # with the reason, exactly like the capture-dead branch. (Probe ONCE so a
                # stateful probe can't report a different reason than it gated on.)
                err_reason = dr_reason or "mouse delivery unavailable"
                to_stop = self._fail_delivery_locked(err_reason)
                emit_states = dict(self._states)
                emit_error = True
            elif now_active:
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
                    self._clear_hover_locked()
                    self._set_states_locked({
                        s: ("error" if s in self._members else "off")
                        for s in range(SLOT_COUNT)
                    })
                    emit_states = dict(self._states)
                    emit_error = True
                    err_reason = "mouse capture stopped unexpectedly"
            else:
                to_stop, self._capture = self._capture, None
            emit_gen = self._states_gen
        # Outside the lock from here. Emit BEFORE stop(): stop can block on
        # a thread join and must not delay the UI state flip.
        if emit_states is not None:
            self._emit_if_current(
                emit_states, emit_gen,
                error_msg=(err_reason if emit_error else None),
                trace_msg=(("service error: " + err_reason)
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
            self._clear_hover_locked()
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
            self._clear_hover_locked()
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
        pending, self._hover_pending = self._hover_pending, None
        if pending is not None and "active" in self._states.values():
            now = monotonic()
            self._hover_last_emit = now
            self._emit_hover_locked(*pending, now)
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
        # (b) pre-press: refuse to start a gesture into unavailable delivery.
        p_ready, p_reason = self._delivery_ready()
        if not p_ready:
            p_err = p_reason or "mouse delivery unavailable"
            to_stop = self._fail_delivery_locked(p_err)
            fail_states = dict(self._states)
            fail_gen = self._states_gen
            if to_stop is not None:
                threading.Thread(target=to_stop.stop, daemon=True).start()
            self._emit_if_current(fail_states, fail_gen,
                                  error_msg=p_err,
                                  trace_msg=f"service error: {p_err}")
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
                # (c) sticky: a press that failed AND left delivery not-ready
                # stops NOW rather than waiting for the next recompute tick.
                if not self._delivery_ready()[0]:
                    c_err = "mouse delivery faulted mid-gesture"
                    to_stop = self._fail_delivery_locked(c_err)
                    fail_states = dict(self._states)
                    fail_gen = self._states_gen
                    if to_stop is not None:
                        threading.Thread(target=to_stop.stop, daemon=True).start()
                    self._emit_if_current(fail_states, fail_gen,
                                          error_msg=c_err,
                                          trace_msg=f"service error: {c_err}")
                    return
        if not delivered:
            return
        self._gesture = Gesture(
            source_slot=src_slot, source_geom=src_geom,
            press_root=(root_x, root_y), press_state=state,
            press_time=time, targets=delivered)
        self._last_motion_emit = 0.0
        self._pending_motion = None
        self._hover_source = None    # re-latch via normal motion post-gesture
        self._hover_rejected = None  # the press just confirmed this point
        self.ghost_pointer_event.emit(
            ("press", [(slot, g0[0] + tx, g0[1] + ty)
                       for slot, (_wid, g0, (tx, ty)) in delivered.items()]))

    def _handle_motion_locked(self, root_x, root_y, state, time):
        if self._gesture is None:
            self._handle_hover_locked(root_x, root_y, state, time)
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
        ghosts = []
        for slot, (wid, geom, _) in g.targets.items():
            tx, ty = map_point(g.source_geom, geom, root_x, root_y)
            # Return value intentionally ignored (spec deviation, recorded
            # there): a target dying mid-gesture is reclaimed by window
            # re-detection and the next geometry tick within ~2s.
            self._backend.send_motion(
                wid, tx, ty, geom[0] + tx, geom[1] + ty, state=state, time=time)
            ghosts.append((slot, geom[0] + tx, geom[1] + ty))
        if ghosts:
            self.ghost_pointer_event.emit(("motion", ghosts))

    # ── hover forwarding (no gesture; lock held) ───────────────────────

    def _handle_hover_locked(self, root_x, root_y, state, time):
        if "active" not in self._states.values():
            return
        if state & HELD_BUTTONS_MASK:
            # A button is held but no synced gesture exists (the press
            # landed outside the members, or it is a non-left button):
            # that is a drag, not hover. Forwarding it would deliver
            # drag-mask motion to targets that never saw the press.
            return
        now = monotonic()
        if now - self._hover_last_emit < MOTION_COALESCE_S:
            self._hover_pending = (root_x, root_y, state, time)
            self._schedule_hover_flush_locked()
            return
        self._hover_last_emit = now
        self._hover_pending = None
        self._emit_hover_locked(root_x, root_y, state, time, now)

    def _emit_hover_locked(self, root_x, root_y, state, time, now,
                           allow_confirm=True):
        """Forward one coalesced hover sample. CACHED geometry on both
        sides — zero X round trips in the steady state; the authoritative
        resolver runs at most once per HOVER_CONFIRM_S (see
        _resolve_hover_source_locked).

        allow_confirm=False is the trailing-flush path (timer thread): the
        production resolver opens a per-thread X Display, so the flush
        never confirms — an unlatched candidate is dropped, a latched one
        forwards on its (16ms-stale) latch."""
        wids_by_slot = self._member_wids_locked()
        geoms = {}
        for s, wid in wids_by_slot.items():
            g = self._geometry_provider(wid)
            if g is not None:
                geoms[s] = g
        src = self._resolve_hover_source_locked(
            wids_by_slot, geoms, root_x, root_y, now, allow_confirm)
        if src is None:
            return
        src_slot, src_wid = src
        src_geom = geoms[src_slot]
        ghosts = []
        for s, wid in wids_by_slot.items():
            if s == src_slot or wid == src_wid:
                continue  # echo guard: never inject back into the source
            g = geoms.get(s)
            if g is None or g[2] <= 0 or g[3] <= 0:
                continue
            tx, ty = map_point(src_geom, g, root_x, root_y)
            # Return value ignored (same as gesture motion): a dying target
            # is reclaimed by window re-detection within ~2s.
            self._backend.send_motion(
                wid, tx, ty, g[0] + tx, g[1] + ty, state=state, time=time)
            ghosts.append((s, g[0] + tx, g[1] + ty))
        if ghosts:
            self.ghost_pointer_event.emit(("motion", ghosts))

    def _resolve_hover_source_locked(self, wids_by_slot, geoms,
                                     root_x, root_y, now, allow_confirm):
        """Pick the hover source for this sample. Returns (slot, wid) or
        None (nothing forwards this tick). The authoritative resolver is
        called at most once per HOVER_CONFIRM_S in EVERY outcome class:
        successful latches, rejected candidates (an occluded member must
        not re-confirm at the emit rate), and overlap corrections (a fresh
        latch wins over the rect pick while the cursor stays inside it —
        otherwise overlapping member rects would re-confirm every tick,
        because the rect test keeps picking the lower slot the resolver
        just corrected away from)."""
        fresh = now - self._hover_last_confirm < HOVER_CONFIRM_S
        latched = self._hover_source
        if latched is not None and fresh:
            s, wid = latched
            g = geoms.get(s)
            if (wids_by_slot.get(s) == wid and g is not None
                    and rect_hit_test({s: g}, root_x, root_y) == s):
                return latched
        cand = rect_hit_test(geoms, root_x, root_y)
        if cand is None:
            self._hover_source = None
            return None
        cand_wid = wids_by_slot[cand]
        if not allow_confirm:
            return latched if latched == (cand, cand_wid) else None
        if fresh and self._hover_rejected == (cand, cand_wid):
            return None  # recently rejected: retry only after the interval
        resolved = self._source_resolver(
            root_x, root_y, list(wids_by_slot.values()))
        self._hover_last_confirm = now  # one stamp throttles latch AND reject
        if resolved != cand_wid:
            other = next((s2 for s2, w2 in wids_by_slot.items()
                          if w2 == resolved), None)
            if other is None or geoms.get(other) is None:
                # Non-member on top, clean miss, or resolver failure: all
                # best-effort misses — never latch _service_failed.
                _trace(f"hover confirm miss cand={cand_wid} got={resolved!r}")
                self._hover_source = None
                self._hover_rejected = (cand, cand_wid)
                return None
            # Another MEMBER is on top (overlapping member rects): the
            # authoritative answer wins over the rect pick.
            cand, cand_wid = other, resolved
        self._hover_source = (cand, cand_wid)
        self._hover_rejected = None
        return self._hover_source

    def _schedule_hover_flush_locked(self):
        """Trailing flush: hover has no release event, but the final resting
        position decides which menu item stays highlighted. One timer in
        flight is enough — it reads whatever sample is pending when it
        fires. Each timer owns its slot via identity check in _hover_flush,
        so a fired-but-lock-blocked old timer cannot steal a newer sample."""
        if self._hover_flush_timer is not None:
            return
        t = threading.Timer(MOTION_COALESCE_S, lambda: self._hover_flush(t))
        t.daemon = True
        t.start()
        self._hover_flush_timer = t

    def _hover_flush(self, t):
        with self._lock:
            if self._hover_flush_timer is not t:
                return  # superseded/cancelled: a newer owner has the sample
            self._hover_flush_timer = None
            pending, self._hover_pending = self._hover_pending, None
            if (pending is None or self._shutdown or not self._enabled
                    or self._gesture is not None
                    or "active" not in self._states.values()):
                return
            now = monotonic()
            self._hover_last_emit = now
            self._emit_hover_locked(*pending, now, allow_confirm=False)

    def _clear_hover_locked(self):
        self._hover_source = None
        self._hover_rejected = None
        self._hover_pending = None
        self._hover_last_emit = 0.0
        self._hover_last_confirm = 0.0
        t, self._hover_flush_timer = self._hover_flush_timer, None
        if t is not None:
            t.cancel()
        self.ghost_clear.emit()

    def _handle_release_locked(self, root_x, root_y, state, time):
        if self._gesture is None:
            return
        if self._pending_motion is not None:
            self._emit_motion_locked(*self._pending_motion)
            self._pending_motion = None
        g, self._gesture = self._gesture, None
        _trace(f"release -> {len(g.targets)} targets")
        ghosts = []
        for slot, (wid, geom, _) in g.targets.items():
            tx, ty = map_point(g.source_geom, geom, root_x, root_y)
            self._backend.send_button_release(
                wid, tx, ty, geom[0] + tx, geom[1] + ty, state=state, time=time)
            ghosts.append((slot, geom[0] + tx, geom[1] + ty))
        if ghosts:
            self.ghost_pointer_event.emit(("release", ghosts))

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
