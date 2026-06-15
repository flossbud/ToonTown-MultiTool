"""macOS input backend: posts synthetic keyboard events to a specific game
window's owning process via CGEventPostToPid. Window-ID-keyed externally (to
match XlibBackend/Win32Backend); PID-resolved internally. Lazy PyObjC."""
from __future__ import annotations

import time

from utils import macos_keycodes as _mk

SPIKE_EVENT_TAG = 0x7474_6D74  # kCGEventSourceUserData marker (echo insurance)
# A just-closed TTR window's dead PID is a harmless CGEventPostToPid no-op, and
# trusted-bundle-on-first-sight catches PID/window-id identity reuse, so a small
# residual staleness window is acceptable. 0.25s keeps reuse exposure tiny while
# still avoiding a full enumeration on every keystroke.
_CACHE_TTL = 0.25
# CGPreflightPostEventAccess cache TTL. Accessibility (post) permission is
# revocable at runtime, so re-check on a cadence rather than once at connect.
_ACCESS_TTL = 1.0
# X.Button1Mask in the service's X-style state mask (matches services.click_sync_service).
_BUTTON1_MASK = 0x100


class MacOSBackend:
    def __init__(self):
        self._source = None
        self._cache = {"t": -1.0, "valid": {}}  # wid_str -> (pid, bundle_id)
        self._trusted = {}  # wid_str -> bundle_id (first-sight identity lock)
        self._access = {"t": -1.0, "ok": True}  # CGPreflightPostEventAccess cache
        self._delivery = None             # MacOSMouseDelivery (lazy)
        self._echo_ledger = None          # shared EchoLedger (Task 8 wires it; the engine records into it)
        self._bindings = {}               # wid_str -> (pid, wid, psn, owner, creation) for the live gesture

    def _quartz(self):
        import Quartz
        return Quartz

    def connect(self):
        Q = self._quartz()
        self._source = Q.CGEventSourceCreate(Q.kCGEventSourceStateCombinedSessionState)

    def disconnect(self):
        self._source = None
        self._cache = {"t": -1.0, "valid": {}}
        self._trusted = {}
        self._access = {"t": -1.0, "ok": True}
        self._delivery = None             # drop engine (clears any sticky delivery fault)
        self._bindings = {}

    def has_post_access(self) -> bool:
        """Whether this process currently has permission to POST synthetic events
        (Accessibility). CGEventPostToPid SILENTLY no-ops without it, so readiness
        must treat False as not-deliverable: otherwise strict suppression would
        suppress native movement while delivery fails, FREEZING the focused toon.
        Cached for _ACCESS_TTL (TCC is revocable). Acts only on a DETECTED denial
        (preflight returns False); a check error or a missing symbol (older macOS)
        is treated as access-OK so a transient check glitch never disables a
        working setup."""
        now = time.monotonic()
        if now - self._access["t"] <= _ACCESS_TTL:
            return self._access["ok"]
        ok = True
        try:
            Q = self._quartz()
            preflight = getattr(Q, "CGPreflightPostEventAccess", None)
            if preflight is not None:
                ok = bool(preflight())
        except Exception:
            ok = True
        self._access = {"t": now, "ok": ok}
        return ok

    def sync(self):
        pass

    def _refresh(self):
        from utils import macos_discovery
        now = time.time()
        if now - self._cache["t"] > _CACHE_TTL:
            try:
                self._cache["valid"] = {
                    str(r.window_id): (r.pid, r.bundle_id)
                    for r in macos_discovery._enumerate_game_windows()
                }
            except Exception:
                # Never propagate enumeration failures into a keystroke path;
                # treat as "no valid targets" until the next refresh succeeds.
                self._cache["valid"] = {}
            self._cache["t"] = now
        return self._cache["valid"]

    def _resolve_pid(self, win_id_str: str):
        """Owner PID for a current game window id (interval-cached), or None.

        Trusted-bundle-on-first-sight: the first time a window id is seen its
        bundle id is recorded. If the window id later resolves to a different
        bundle, the PID/window-id was reused by another app and we refuse to
        post (returns None). A window id that disappears clears its trust."""
        wid = str(win_id_str)
        entry = self._refresh().get(wid)
        if entry is None:
            self._trusted.pop(wid, None)
            return None
        pid, bundle = entry
        trusted = self._trusted.get(wid, "__unset__")
        if trusted == "__unset__":
            self._trusted[wid] = bundle  # first sight
            return pid
        if trusted != bundle:
            self._trusted.pop(wid, None)  # identity reuse caught
            return None
        return pid

    def get_window_pid(self, win_id_str: str):
        return self._resolve_pid(win_id_str)

    def get_window_x(self, win_id_str: str):
        from utils import macos_discovery
        return macos_discovery.get_window_root_x(win_id_str)

    def _post_to_pid(self, pid: int, vk: int, down: bool, flags: int = 0) -> bool:
        try:
            Q = self._quartz()
            ev = Q.CGEventCreateKeyboardEvent(self._source, vk, bool(down))
            if ev is None:
                return False
            Q.CGEventSetIntegerValueField(ev, Q.kCGEventSourceUserData, SPIKE_EVENT_TAG)
            # Always set flags (even 0) to clear any ambient combined-session
            # modifier state that would otherwise leak into an unmodified send.
            Q.CGEventSetFlags(ev, flags)
            Q.CGEventPostToPid(pid, ev)
            return True
        except Exception:
            return False

    def _send_once(self, win_id_str, keysym_str, down, flags=0) -> bool:
        vk = _mk.cgkeycode_for_keysym(keysym_str)
        if vk is None:
            return False
        pid = self._resolve_pid(win_id_str)
        if pid is None:
            return False
        return self._post_to_pid(pid, vk, down, flags)

    def send_keydown(self, win_id_str, keysym_str, state=0) -> bool:
        return self._send_once(win_id_str, keysym_str, True)

    def send_keyup(self, win_id_str, keysym_str, state=0) -> bool:
        return self._send_once(win_id_str, keysym_str, False)

    def send_key(self, win_id_str, keysym_str, modifiers=None) -> bool:
        flags = _mk.flags_for_modifiers(modifiers)
        vk = _mk.cgkeycode_for_keysym(keysym_str)
        if vk is None:
            return False
        pid = self._resolve_pid(win_id_str)  # resolve ONCE
        if pid is None:
            return False
        down_ok = self._post_to_pid(pid, vk, True, flags)
        # Always attempt the up to the same pid, even if the down failed, so a
        # half-completed send never leaves a key stuck down.
        up_ok = self._post_to_pid(pid, vk, False, flags)
        return down_ok and up_ok

    def _engine(self):
        if self._delivery is None:
            from utils.macos_mouse_delivery import MacOSMouseDelivery
            self._delivery = MacOSMouseDelivery(ledger=self._echo_ledger)
        return self._delivery

    def set_echo_ledger(self, ledger):
        """Share the EchoLedger the capture uses, so every posted event is recorded for
        the capture's marker-stripped-echo detection (Task 8 wires the SAME instance into
        the backend + the capture). Rebuilds the engine so it picks the ledger up."""
        self._echo_ledger = ledger
        self._delivery = None

    def mouse_delivery_ready(self):
        """(ready: bool, reason: str | None). SEPARATE from has_post_access() so a
        mouse-SPI break never disables working keyboard delivery (spec §3.2/§3.5).
        Fail-CLOSED: ANY probe error (e.g. the engine's lazy import raising) returns
        not-ready with a reason, NEVER ready (mirrors _creation_identity's discipline)."""
        try:
            if not self.has_post_access():
                return (False, "accessibility (post-event) access not granted")
            if not self._engine().available:
                return (False, "macOS per-window mouse delivery unavailable "
                               "(private SkyLight symbols missing or a delivery fault)")
            return (True, None)
        except Exception as e:
            return (False, f"mouse delivery probe failed: {type(e).__name__}: {e}")

    def _creation_identity(self, pid):
        """A stable per-process token (NSRunningApplication launch date) so a reused PID
        is detectable across a gesture. None if unavailable. Never raises."""
        try:
            from AppKit import NSRunningApplication
            app = NSRunningApplication.runningApplicationWithProcessIdentifier_(int(pid))
            if app is None:
                return None
            launched = app.launchDate()
            return None if launched is None else float(launched.timeIntervalSince1970())
        except Exception:
            return None

    def _resolve_target(self, win_id_str):
        """(pid, window_id_int, psn, owner_conn, creation_identity) for a current trusted
        game window, or None. owner_conn + creation_identity freeze the gesture against
        same-bundle PID/window-id reuse (all TTR toons share ONE bundle, so the trusted-
        bundle lock in _resolve_pid is not enough to catch a different toon reusing a wid)."""
        pid = self._resolve_pid(win_id_str)
        if pid is None:
            return None
        try:
            wid = int(win_id_str)
        except (TypeError, ValueError):
            return None
        psn = self._engine().resolve_psn(wid)
        if psn is None:
            return None
        return (pid, wid, psn, self._engine().resolve_owner(wid), self._creation_identity(pid))

    def send_button_press(self, win_id_str, x, y, root_x, root_y,
                          button=1, state=0, time=0) -> bool:
        target = self._resolve_target(win_id_str)
        if target is None:
            return False
        pid, wid, psn, owner, creation = target
        ok = self._engine().press(pid, wid, psn, (x, y), (root_x, root_y))
        if ok:
            self._bindings[str(win_id_str)] = (pid, wid, psn, owner, creation)   # freeze identity
        return ok

    def send_button_release(self, win_id_str, x, y, root_x, root_y,
                            button=1, state=0, time=0) -> bool:
        bound = self._bindings.pop(str(win_id_str), None)
        if bound is None:
            return False   # never release into a freshly-resolved process (spec §3.2)
        pid, wid, psn, owner, creation = bound
        # Reuse guard: the bound PID must still be the SAME process (same launch identity
        # + owner connection) before we up into it, else a reused wid/pid gets a stray
        # button-up. Mismatch -> drop the up (binding already cleared by pop).
        if (self._creation_identity(pid), self._engine().resolve_owner(wid)) != (creation, owner):
            return False
        return self._engine().release(pid, wid, psn, (x, y), (root_x, root_y))

    def send_motion(self, win_id_str, x, y, root_x, root_y,
                    state=0, time=0) -> bool:
        dragging = bool(state & _BUTTON1_MASK)   # left-button held = the drag we mirror
        if dragging:
            bound = self._bindings.get(str(win_id_str))
            if bound is None:
                return False   # a drag with NO press binding is DROPPED, never fresh-resolved (spec §3.2)
            pid, wid, psn, _owner, _creation = bound       # frozen press binding
            return self._engine().motion(pid, wid, psn, (x, y), (root_x, root_y), dragging=True)
        # HOVER (no button held): fresh-resolve (no gesture binding exists for hover)
        target = self._resolve_target(win_id_str)
        if target is None:
            return False
        pid, wid, psn, _owner, _creation = target
        return self._engine().motion(pid, wid, psn, (x, y), (root_x, root_y), dragging=False)
