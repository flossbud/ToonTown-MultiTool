"""Click sync: mirror left-button gestures between same-aspect TTR windows.

Observe-only capture (XRecord), per-gesture geometry snapshot, XSendEvent
injection. Spec: docs/superpowers/specs/2026-06-10-click-sync-design.md.

Threading: capture events arrive on the XRecord thread; UI calls arrive on
the GUI thread. ALL state mutation goes through self._lock. Qt signals are
emitted while NOT holding the lock (queued delivery to the GUI is fine).
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


def _trace_enabled() -> bool:
    return bool(os.environ.get("TTMT_INPUT_TRACE"))


def _trace(msg: str) -> None:
    if _trace_enabled():
        print(f"[click] {msg}", flush=True)


class ClickSyncService(QObject):
    # {slot: "off"|"armed"|"active"|"error"}; emitted on every state change.
    slot_states_changed = Signal(dict)
    # Emitted once if the capture backend dies / cannot start.
    service_error = Signal(str)

    def __init__(self, slot_window_resolver, geometry_provider,
                 source_resolver, backend, capture_factory, parent=None):
        """slot_window_resolver(slot:int) -> wid|None
        geometry_provider(wid:str) -> (x, y, w, h)|None  (fresh-enough query)
        source_resolver(root_x, root_y, member_wids:list) -> wid|None
            (stacking-aware hit test; see wire-up in Task 9)
        backend: object with send_button_press/send_button_release/send_motion
        capture_factory(on_event) -> object with start()/stop()/is_running()
        """
        super().__init__(parent)
        self._slot_window_resolver = slot_window_resolver
        self._geometry_provider = geometry_provider
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

    # ── public API (GUI thread) ────────────────────────────────────────

    def set_enabled(self, enabled: bool) -> None:
        """Master switch. Disabling drains + pauses but RETAINS membership
        (spec: OFF -> ON in the same session restores the group)."""
        with self._lock:
            if self._enabled == bool(enabled):
                return
            self._enabled = bool(enabled)
            if not self._enabled:
                self._drain_locked("master disabled")
        self.recompute()

    def toggle_slot(self, slot: int) -> bool:
        """Flip group membership for a toon slot. Returns new membership."""
        with self._lock:
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
        and the periodic geometry tick."""
        emit_states = None
        emit_error = None
        cap = None
        with self._lock:
            if self._shutdown:
                return
            if not self._enabled:
                new_states = {s: "off" for s in range(SLOT_COUNT)}
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
                self._states = new_states
                emit_states = dict(new_states)
            if now_active and (self._capture is None or not self._capture.is_running()):
                self._capture = self._capture_factory(self._on_capture_event)
                if not self._capture.start():
                    emit_error = "mouse capture unavailable"
                    self._states = {
                        s: ("error" if s in self._members else "off")
                        for s in range(SLOT_COUNT)
                    }
                    emit_states = dict(self._states)
            elif not now_active and self._capture is not None and self._capture.is_running():
                cap = self._capture
                self._capture = None
        # Outside the lock: Qt signals + capture stop (stop() joins a thread).
        if cap is not None:
            cap.stop()
        if emit_states is not None:
            self.slot_states_changed.emit(emit_states)
        if emit_error is not None:
            _trace(f"service error: {emit_error}")
            self.service_error.emit(emit_error)

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

    def notify_capture_died(self) -> None:
        """Hooked to XRecordCapture's on_died: the capture thread died
        unexpectedly. Stop the capture (NEVER just drop the reference: the
        dead capture still holds two X connections and dropping it leaks
        client slots — stop() is safe to call from the capture thread
        itself), drain, and drop to a service-level error state (member
        buttons show error; keyboard routing unaffected)."""
        with self._lock:
            if self._shutdown:
                return
            self._drain_locked("capture died")
            cap, self._capture = self._capture, None
            self._states = {
                s: ("error" if s in self._members else "off")
                for s in range(SLOT_COUNT)
            }
            states = dict(self._states)
        if cap is not None:
            cap.stop()
        _trace("service error: capture died")
        self.slot_states_changed.emit(states)
        self.service_error.emit("mouse capture stopped unexpectedly")

    # ── capture events (XRecord thread) ────────────────────────────────

    def _on_capture_event(self, kind: str, root_x: int, root_y: int,
                          state: int, time: int) -> None:
        with self._lock:
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
        src_geom = self._geometry_provider(src_wid)
        if src_geom is None:
            return
        targets = {}
        for s, wid in wids_by_slot.items():
            if s == src_slot:
                continue
            g = self._geometry_provider(wid)
            if g is None:
                continue
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
            # state = press state with Button1Mask (0x100), press timestamp.
            self._backend.send_button_release(
                wid, tx, ty, geom[0] + tx, geom[1] + ty,
                state=g.press_state | 0x100, time=g.press_time)
