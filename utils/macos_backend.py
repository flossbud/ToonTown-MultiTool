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


class MacOSBackend:
    def __init__(self):
        self._source = None
        self._cache = {"t": -1.0, "valid": {}}  # wid_str -> (pid, bundle_id)
        self._trusted = {}  # wid_str -> bundle_id (first-sight identity lock)

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

    def send_button_press(self, win_id_str, x, y, root_x, root_y,
                          button=1, state=0, time=0) -> bool:
        return False

    def send_button_release(self, win_id_str, x, y, root_x, root_y,
                            button=1, state=0, time=0) -> bool:
        return False

    def send_motion(self, win_id_str, x, y, root_x, root_y,
                    state=0, time=0) -> bool:
        return False
