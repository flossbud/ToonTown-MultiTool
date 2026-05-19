"""X11 passive grab on selected keysyms.

Why: CC's executable accepts both WASD and arrow keys for movement and
ignores attempts to remove arrows from its preferences.json keymap.
Locking CC to a single canonical keyset only works for the BACKGROUND
toon (which TTMT controls via the wine bridge). The FOCUSED window
still receives the conflicting keyset natively because the OS delivers
the keystroke before CC has a chance to filter it.

This module installs a passive XGrabKey for the conflicting keyset
(e.g. arrows when canonical=WASD). When a grabbed key fires, the X
server delivers it to TTMT first. A per-event callback decides whether
to:
  - consume the event (the key never reaches the focused window) and
    route it via TTMT's existing input pipeline, or
  - replay it via XAllowEvents(ReplayKeyboard) so the focused window
    receives it normally (e.g. when CC chat is open and the user is
    moving the chat cursor with arrows).

The grab is global to the X server. python-xlib is the same dep used
by utils/x11_discovery.py; no new requirements. Under XWayland the
grab still works for X11 client windows (CC under wine is X11), but
native Wayland windows are out of scope and unaffected.
"""

from __future__ import annotations

import threading
from typing import Callable, Optional

try:
    from Xlib import display as _xlib_display, X, XK
    from Xlib.error import BadAccess, ConnectionClosedError
    _HAS_XLIB = True
except ImportError:
    _HAS_XLIB = False


# Full modifier permutations. XGrabKey registers a grab for an exact
# modifier mask, so we must enumerate every combination of the three
# common lock states (Caps, Num, Scroll) AND every combination of the
# user-controlled modifiers (Shift, Ctrl, Alt) the user might be in.
# Without the lock combos the grab silently misses when, e.g., NumLock
# is on. Without the user-modifier combos the grab silently misses
# when, e.g., the user is holding Shift to sprint (so Shift+Up reaches
# the focused CC window and moves the wrong toon).
def _modifier_combos():
    if not _HAS_XLIB:
        return ()
    locks = (0, X.LockMask, X.Mod2Mask, X.Mod5Mask)
    user_mods = (0, X.ShiftMask, X.ControlMask, X.Mod1Mask)
    lock_combos = set()
    for a in locks:
        for b in locks:
            for c in locks:
                lock_combos.add(a | b | c)
    user_combos = set()
    for a in user_mods:
        for b in user_mods:
            for c in user_mods:
                user_combos.add(a | b | c)
    combos = set()
    for lc in lock_combos:
        for uc in user_combos:
            combos.add(lc | uc)
    return tuple(sorted(combos))


_LOCK_MODIFIERS = _modifier_combos()


def xlib_available() -> bool:
    """Probe whether the module can do anything at all."""
    return _HAS_XLIB


class MovementKeyGrabber:
    """Lifecycle: construct, call start() once with the keysyms + callbacks,
    call stop() before exit. Idempotent: start() while running is a no-op,
    stop() while stopped is a no-op."""

    def __init__(self):
        self._display = None
        self._root = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._grabbed: list[tuple[int, int]] = []
        # Map keycode -> (kind, keysym_name) where kind is "grabbed"
        # (events get consumed and routed via on_key) or "passthrough"
        # (events arrive at our grab during the active-grab window and
        # we hand them to on_passthrough so the focused window doesn't
        # lose control of WASD/modifiers/etc. while an arrow is held).
        # XK.keysym_to_string would return None for non-printable
        # keysyms like Up/Down/Left/Right, so we build this map at
        # start() from the keysyms we explicitly register.
        self._keycode_to_name: dict[int, tuple[str, str]] = {}
        self._on_key: Optional[Callable[[str, str], None]] = None
        self._on_passthrough: Optional[Callable[[str, str], None]] = None
        self._should_consume: Optional[Callable[[str], bool]] = None

    def start(
        self,
        keysyms: list[str],
        on_key: Callable[[str, str], None],
        should_consume: Callable[[str], bool],
        passthrough_keysyms: Optional[list[str]] = None,
        on_passthrough: Optional[Callable[[str, str], None]] = None,
    ) -> bool:
        """Register passive grabs for each keysym and start the event-loop
        thread. Returns True on success, False if xlib is unavailable, the
        display can't be opened, or the grabber is already running.

        passthrough_keysyms is the list of OTHER keys we want to recognize
        when they arrive at our grab during the active-grab window (e.g.
        WASD pressed while an arrow is held). For those we don't establish
        a passive grab, but we DO record their keycode so the event loop
        can route them via on_passthrough. Without this the user loses
        control of the focused window while an arrow is held because the
        X server redirects all keyboard events to the grabbing client
        during the active grab, and AllowEvents(ReplayKeyboard) is a no-op
        when keyboard_mode is Async.
        """
        if not _HAS_XLIB:
            return False
        if self._thread is not None and self._thread.is_alive():
            return True

        try:
            self._display = _xlib_display.Display()
        except Exception as e:  # noqa: BLE001
            print(f"[x11_movement_grabber] cannot open display: {e}")
            return False

        self._root = self._display.screen().root
        self._on_key = on_key
        self._on_passthrough = on_passthrough
        self._should_consume = should_consume

        registered = 0
        for keysym_name in keysyms:
            ks = XK.string_to_keysym(keysym_name)
            if ks == 0:
                print(f"[x11_movement_grabber] unknown keysym {keysym_name!r}; skipped")
                continue
            keycode = self._display.keysym_to_keycode(ks)
            if keycode == 0:
                continue
            self._keycode_to_name[keycode] = ("grabbed", keysym_name)
            for mod in _LOCK_MODIFIERS:
                try:
                    self._root.grab_key(
                        keycode, mod, True,
                        X.GrabModeAsync, X.GrabModeAsync,
                    )
                    self._grabbed.append((keycode, mod))
                    registered += 1
                except BadAccess:
                    # Another client already grabbed this combo. Not fatal -
                    # we just won't suppress that exact key+mod combo.
                    pass

        for keysym_name in passthrough_keysyms or []:
            ks = XK.string_to_keysym(keysym_name)
            if ks == 0:
                continue
            keycode = self._display.keysym_to_keycode(ks)
            if keycode == 0:
                continue
            # Don't overwrite a grabbed entry if it happens to share a keycode.
            self._keycode_to_name.setdefault(keycode, ("passthrough", keysym_name))

        try:
            self._display.sync()
        except Exception as e:  # noqa: BLE001
            print(f"[x11_movement_grabber] sync after grab failed: {e}")

        if registered == 0:
            self._cleanup_display()
            return False

        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="MovementKeyGrabber"
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None
        self._cleanup_display()

    def _cleanup_display(self) -> None:
        if self._display is not None:
            for keycode, mod in self._grabbed:
                try:
                    self._root.ungrab_key(keycode, mod)
                except Exception:
                    pass
            try:
                self._display.sync()
            except Exception:
                pass
            try:
                self._display.close()
            except Exception:
                pass
            self._display = None
            self._root = None
            self._grabbed = []
            self._keycode_to_name = {}

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                pending = self._display.pending_events()
            except Exception:
                break
            if pending == 0:
                self._stop.wait(0.01)
                continue
            try:
                event = self._display.next_event()
            except (ConnectionClosedError, OSError):
                break

            if event.type not in (X.KeyPress, X.KeyRelease):
                continue

            # Auto-repeat detection. X11 represents auto-repeat as a
            # KeyRelease immediately followed by a KeyPress for the same
            # key at the same timestamp. Without this dedup, every
            # auto-repeat tick fires a keyup+keydown to the routed toon,
            # which manifests as the bridge spamming rapid press/release
            # cycles instead of one held key. We treat any matched pair as
            # "no event" (the key is still logically held; no new keydown,
            # no real keyup) and let the InputService's existing
            # keys_held set keep the held state.
            if event.type == X.KeyRelease:
                try:
                    next_pending = self._display.pending_events()
                except Exception:
                    next_pending = 0
                if next_pending > 0:
                    try:
                        next_event = self._display.next_event()
                    except (ConnectionClosedError, OSError):
                        break
                    is_autorepeat = (
                        next_event.type == X.KeyPress
                        and next_event.detail == event.detail
                        and next_event.time == event.time
                    )
                    if is_autorepeat:
                        # Drop both halves of the auto-repeat pair.
                        # AllowEvents on the release's time keeps X
                        # processing happy; no callback fires.
                        try:
                            self._display.allow_events(X.AsyncKeyboard, event.time)
                            self._display.sync()
                        except Exception:
                            break
                        continue
                    else:
                        # Not auto-repeat. Process the release we already
                        # popped, then loop back so the next iteration
                        # picks up next_event from the queue... but we
                        # consumed it, so process it inline here too.
                        self._handle_event(event)
                        self._handle_event(next_event)
                        continue

            self._handle_event(event)

    def _handle_event(self, event) -> None:
        """Decide consume / passthrough / replay for a single key event."""
        entry = self._keycode_to_name.get(event.detail)
        kind = entry[0] if entry else None
        keysym_name = entry[1] if entry else None

        consume = False
        if kind == "grabbed" and self._should_consume is not None:
            try:
                consume = bool(self._should_consume(keysym_name))
            except Exception as e:  # noqa: BLE001
                print(f"[x11_movement_grabber] should_consume raised: {e}")
                consume = False

        mode = X.AsyncKeyboard if consume else X.ReplayKeyboard
        try:
            self._display.allow_events(mode, event.time)
            self._display.sync()
        except Exception:
            return

        action = "keydown" if event.type == X.KeyPress else "keyup"
        if consume and self._on_key is not None:
            try:
                self._on_key(action, keysym_name)
            except Exception as e:  # noqa: BLE001
                print(f"[x11_movement_grabber] on_key raised: {e}")
        elif keysym_name and self._on_passthrough is not None:
            # Fall through to passthrough for two cases:
            #  - kind == "passthrough" (key registered as passthrough only)
            #  - kind == "grabbed" but should_consume returned False (e.g.
            #    chat is active so arrows should reach the focused chat
            #    box for cursor movement). ReplayKeyboard is a no-op in
            #    GrabModeAsync, so without this hand-off the key would
            #    vanish.
            try:
                self._on_passthrough(action, keysym_name)
            except Exception as e:  # noqa: BLE001
                print(f"[x11_movement_grabber] on_passthrough raised: {e}")
