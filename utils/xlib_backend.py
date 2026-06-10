"""
Xlib-based input backend for ToonTown MultiTool.

Replaces xdotool keydown/keyup/key calls with direct Xlib send_event calls
from within the Python process. Since the process is already authorized
through the GNOME RemoteDesktop portal, no per-subprocess auth dialogs
appear.

Window discovery still uses xdotool (search, getwindowpid) as those don't
trigger the portal. Geometry lookups use Xlib directly (fix #6).
"""

from __future__ import annotations

from Xlib import display as xdisplay, X, XK, error
from Xlib.protocol import event as xevent


# Map xdotool-style modifier names to X modifier masks
MODIFIER_MASKS = {
    "shift":   X.ShiftMask,
    "ctrl":    X.ControlMask,
    "alt":     X.Mod1Mask,
}


class XlibBackend:
    def __init__(self):
        self._display = None

    def connect(self):
        self._display = xdisplay.Display()

    def disconnect(self):
        if self._display:
            try:
                self._display.close()
            except Exception as e:
                print(f"[XlibBackend] Failed to close display: {e}")
            self._display = None

    def get_window_x(self, win_id_str: str) -> int | None:
        """Get window X position via Xlib — no subprocess needed.

        Returns the raw translate_coords value. On XWayland compositors this
        may be negated; the caller (assign_windows) corrects for that by
        looking at all positions as a batch.
        """
        if not self._display:
            return None
        try:
            win = self._display.create_resource_object("window", int(win_id_str))
            coords = win.translate_coords(self._display.screen().root, 0, 0)
            return coords.x
        except Exception:
            return None

    def get_window_pid(self, win_id_str: str) -> int | None:
        """Get the host PID for a window using the XRes extension.

        Returns the real host-namespace PID even for Flatpak/containerized
        clients, since the X server always sees the true PID.
        Returns None if XRes is unavailable or the query fails.
        """
        if not self._display:
            return None
        try:
            if not self._display.has_extension("X-Resource"):
                return None
            from Xlib.ext import res as xres
            wid = int(win_id_str)
            resp = self._display.res_query_client_ids(
                [{"client": wid, "mask": xres.LocalClientPIDMask}]
            )
            for cid in resp.ids:
                if cid.value:
                    return cid.value[0]
        except Exception as e:
            print(f"[XlibBackend] XRes PID query failed for window {win_id_str}: {e}")
        return None

    def _keycode_for(self, keysym_str: str):
        """Convert an xdotool-style keysym string to an X keycode."""
        ks = XK.string_to_keysym(keysym_str)
        if not ks and len(keysym_str) == 1:
            ks = ord(keysym_str)
        if not ks:
            return None
        kc = self._display.keysym_to_keycode(ks)
        return kc if kc else None

    def key_physically_down(self, keysym_str: str):
        """Tri-state physical-key check via XQueryKeymap.

        Returns True if the key is currently held, False if it is up, or None
        when the answer is unknown (no display, unmappable keysym, or query
        failure) so callers can fall back to their default behavior rather than
        guess. Querying the server's keymap is a direct physical-state read and
        is unaffected by the GrabModeAsync movement grab (no freeze). Must be
        called on the thread that owns this Display (the InputService worker,
        same as send_event)."""
        if not self._display:
            return None
        try:
            ks = XK.string_to_keysym(keysym_str)
            if not ks and len(keysym_str) == 1:
                ks = ord(keysym_str)
            if not ks:
                return None
            # All keycodes that map to this keysym (handles duplicate/layout keys).
            keycodes = []
            try:
                for item in self._display.keysym_to_keycodes(ks):
                    kc = item[0] if isinstance(item, (tuple, list)) else item
                    keycodes.append(kc)
            except Exception:
                keycodes = []
            if not keycodes:
                kc = self._display.keysym_to_keycode(ks)
                if kc:
                    keycodes = [kc]
            if not keycodes:
                return None
            km = self._display.query_keymap()
            if not isinstance(km, (list, tuple)) or len(km) != 32:
                return None
            for kc in keycodes:
                if 0 <= kc <= 255 and (km[kc >> 3] & (1 << (kc & 7))):
                    return True
            return False
        except Exception:
            return None

    def _modifier_mask(self, modifiers: list) -> int:
        mask = 0
        for m in modifiers:
            mask |= MODIFIER_MASKS.get(m.lower(), 0)
        return mask

    def _make_event(self, win, event_type, keycode, state=0):
        cls = xevent.KeyPress if event_type == X.KeyPress else xevent.KeyRelease
        return cls(
            time=X.CurrentTime,
            root=self._display.screen().root,
            window=win,
            same_screen=1,
            child=X.NONE,
            root_x=0, root_y=0,
            event_x=0, event_y=0,
            state=state,
            detail=keycode
        )

    def _send(self, win_id_str: str, event_type: int, keysym_str: str, state: int = 0) -> bool:
        if not self._display:
            return False
        try:
            kc = self._keycode_for(keysym_str)
            if not kc:
                return False
            win = self._display.create_resource_object("window", int(win_id_str))
            ev = self._make_event(win, event_type, kc, state)
            win.send_event(ev, propagate=True)
            self._display.flush()
            return True
        except error.BadWindow:
            return False
        except Exception:
            return False

    def send_keydown(self, win_id_str: str, keysym_str: str, state: int = 0) -> bool:
        return self._send(win_id_str, X.KeyPress, keysym_str, state)

    def send_keyup(self, win_id_str: str, keysym_str: str, state: int = 0) -> bool:
        return self._send(win_id_str, X.KeyRelease, keysym_str, state)

    def send_key(self, win_id_str: str, keysym_str: str, modifiers: list = None) -> bool:
        state = self._modifier_mask(modifiers) if modifiers else 0
        if not self._send(win_id_str, X.KeyPress, keysym_str, state): return False
        self._display.flush()
        return self._send(win_id_str, X.KeyRelease, keysym_str, state)

    # ── Pointer events (click sync) ────────────────────────────────────
    # Spike-resolved delivery mode: True = ButtonPressMask/etc.,
    # False = event_mask=0 (deliver to the window's creator client).
    _POINTER_MASKED = True

    def _send_pointer_event(self, win_id_str: str, ev_cls, mask: int,
                            x: int, y: int, root_x: int, root_y: int,
                            detail: int, state: int, time: int) -> bool:
        if not self._display:
            return False
        try:
            win = self._display.create_resource_object("window", int(win_id_str))
            ev = ev_cls(
                # X.CurrentTime == 0; the sentinel passes through verbatim
                # (SendEvent never substitutes server time).
                time=time,
                root=self._display.screen().root,
                window=win,
                same_screen=1,
                child=X.NONE,
                root_x=root_x, root_y=root_y,
                event_x=x, event_y=y,
                state=state,
                detail=detail,
            )
            win.send_event(ev, propagate=False,
                           event_mask=(mask if self._POINTER_MASKED else 0))
            self._display.flush()
            return True
        except error.BadWindow:
            return False
        except Exception:
            return False

    def send_button_press(self, win_id_str: str, x: int, y: int,
                          root_x: int, root_y: int, button: int = 1,
                          state: int = 0, time: int = 0) -> bool:
        return self._send_pointer_event(
            win_id_str, xevent.ButtonPress, X.ButtonPressMask,
            x, y, root_x, root_y, button, state, time)

    def send_button_release(self, win_id_str: str, x: int, y: int,
                            root_x: int, root_y: int, button: int = 1,
                            state: int = 0, time: int = 0) -> bool:
        return self._send_pointer_event(
            win_id_str, xevent.ButtonRelease, X.ButtonReleaseMask,
            x, y, root_x, root_y, button, state, time)

    def send_motion(self, win_id_str: str, x: int, y: int,
                    root_x: int, root_y: int,
                    state: int = 0, time: int = 0) -> bool:
        # Dragging clients select ButtonMotionMask/Button1MotionMask rather
        # than PointerMotionMask; the masked variant must cover all three.
        motion_mask = (X.PointerMotionMask | X.ButtonMotionMask
                       | X.Button1MotionMask)
        return self._send_pointer_event(
            win_id_str, xevent.MotionNotify, motion_mask,
            x, y, root_x, root_y, 0, state, time)

    def sync(self):
        if self._display:
            self._display.sync()
