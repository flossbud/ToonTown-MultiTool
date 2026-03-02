"""
Xlib-based input backend for ToonTown MultiTool.

Replaces xdotool keydown/keyup/key calls with direct Xlib send_event calls
from within the Python process. Since the process is already authorized
through the GNOME RemoteDesktop portal, no per-subprocess auth dialogs
appear.

Window discovery still uses xdotool (search, getwindowgeometry, getwindowpid)
as those don't trigger the portal.
"""

from Xlib import display as xdisplay, X, XK
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
            except Exception:
                pass
            self._display = None

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

    def _send(self, win_id_str: str, event_type: int, keysym_str: str, state: int = 0):
        try:
            kc = self._keycode_for(keysym_str)
            if not kc:
                return
            win = self._display.create_resource_object("window", int(win_id_str))
            ev = self._make_event(win, event_type, kc, state)
            win.send_event(ev, propagate=True)
            self._display.flush()
        except Exception:
            pass

    def send_keydown(self, win_id_str: str, keysym_str: str, state: int = 0):
        self._send(win_id_str, X.KeyPress, keysym_str, state)

    def send_keyup(self, win_id_str: str, keysym_str: str, state: int = 0):
        self._send(win_id_str, X.KeyRelease, keysym_str, state)

    def send_key(self, win_id_str: str, keysym_str: str, modifiers: list = None):
        state = self._modifier_mask(modifiers) if modifiers else 0
        self._send(win_id_str, X.KeyPress, keysym_str, state)
        self._display.flush()
        self._send(win_id_str, X.KeyRelease, keysym_str, state)

    def sync(self):
        if self._display:
            self._display.sync()