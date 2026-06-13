"""macOS input backend: posts synthetic keyboard events to a specific game
window's owning process via CGEventPostToPid. Window-ID-keyed externally (to
match XlibBackend/Win32Backend); PID-resolved internally. Lazy PyObjC."""
from __future__ import annotations

import time

from utils import macos_keycodes as _mk

SPIKE_EVENT_TAG = 0x7474_6D74  # kCGEventSourceUserData marker (echo insurance)
_CACHE_TTL = 1.0


class MacOSBackend:
    def __init__(self):
        self._source = None
        self._cache = {"t": -1.0, "valid": {}}  # wid_str -> (pid, bundle_id)

    def _quartz(self):
        import Quartz
        return Quartz

    def connect(self):
        Q = self._quartz()
        self._source = Q.CGEventSourceCreate(Q.kCGEventSourceStateCombinedSessionState)

    def disconnect(self):
        self._source = None

    def sync(self):
        pass

    def _refresh(self):
        from utils import macos_discovery
        now = time.time()
        if now - self._cache["t"] > _CACHE_TTL:
            self._cache["valid"] = {
                str(r.window_id): (r.pid, r.bundle_id)
                for r in macos_discovery._enumerate_game_windows()
            }
            self._cache["t"] = now
        return self._cache["valid"]

    def _resolve_pid(self, win_id_str: str, expected_bundle="__unset__"):
        """Owner PID for a current game window id (interval-cached), or None.
        When expected_bundle is provided, the PID is returned only if the window's
        current bundle id matches (guards PID/window-id reuse)."""
        entry = self._refresh().get(str(win_id_str))
        if entry is None:
            return None
        pid, bundle = entry
        if expected_bundle != "__unset__" and bundle != expected_bundle:
            return None
        return pid

    def get_window_pid(self, win_id_str: str):
        return self._resolve_pid(win_id_str)

    def get_window_x(self, win_id_str: str):
        from utils import macos_discovery
        return macos_discovery.get_window_root_x(win_id_str)

    def _post(self, pid: int, vk: int, down: bool, flags: int = 0) -> bool:
        Q = self._quartz()
        ev = Q.CGEventCreateKeyboardEvent(self._source, vk, bool(down))
        Q.CGEventSetIntegerValueField(ev, Q.kCGEventSourceUserData, SPIKE_EVENT_TAG)
        if flags:
            Q.CGEventSetFlags(ev, flags)
        Q.CGEventPostToPid(pid, ev)
        return True

    def _send(self, win_id_str, keysym_str, down, flags=0) -> bool:
        vk = _mk.cgkeycode_for_keysym(keysym_str)
        if vk is None:
            return False
        pid = self._resolve_pid(win_id_str)
        if pid is None:
            return False
        return self._post(pid, vk, down, flags)

    def send_keydown(self, win_id_str, keysym_str, state=0) -> bool:
        return self._send(win_id_str, keysym_str, True)

    def send_keyup(self, win_id_str, keysym_str, state=0) -> bool:
        return self._send(win_id_str, keysym_str, False)

    def send_key(self, win_id_str, keysym_str, modifiers=None) -> bool:
        flags = _mk.flags_for_modifiers(modifiers)
        if not self._send(win_id_str, keysym_str, True, flags):
            return False
        return self._send(win_id_str, keysym_str, False, flags)

    def send_button_press(self, *a, **k) -> bool:
        return False

    def send_button_release(self, *a, **k) -> bool:
        return False

    def send_motion(self, *a, **k) -> bool:
        return False
