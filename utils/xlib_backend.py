"""
Xlib-based input backend for ToonTown MultiTool.

Replaces xdotool keydown/keyup/key calls with direct Xlib send_event calls
from within the Python process. Since the process is already authorized
through the GNOME RemoteDesktop portal, no per-subprocess auth dialogs
appear.

Window discovery still uses xdotool (search, getwindowpid) as those don't
trigger the portal. Geometry lookups use Xlib directly (fix #6).
"""

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

    def sync(self):
        if self._display:
            self._display.sync()