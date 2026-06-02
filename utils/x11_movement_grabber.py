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

import queue as _queue
import threading
from typing import Callable, Optional

from utils.input_trace import trace as _itrace, ENABLED as _ITRACE

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

_ALL_MOVEMENT_KEYSYMS = ("w", "a", "s", "d", "Up", "Down", "Left", "Right")


def xlib_available() -> bool:
    """Probe whether the module can do anything at all."""
    return _HAS_XLIB


class MovementKeyGrabber:
    """Lifecycle:
      construct -> prepare() -> install_grabs(set) [...-> uninstall/install_grabs()] -> stop()

    All Xlib mutations happen on the event-loop thread via an internal
    action queue; install_grabs() and uninstall_grabs() are safe to call
    from any thread (typically Qt main thread from the active_window
    signal slot)."""

    def __init__(self):
        self._display = None
        self._root = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._actions: "_queue.Queue[tuple]" = _queue.Queue()
        self._grabbed: list[tuple[int, int]] = []
        self._keycode_to_name: dict[int, tuple[str, str]] = {}
        self._current_canonical: Optional[str] = None
        self._on_key: Optional[Callable[[str, str], None]] = None
        self._on_passthrough: Optional[Callable[[str, str], None]] = None
        self._should_consume: Optional[Callable[[str], bool]] = None
        self._on_grabs_changed: Optional[Callable[[Optional[str]], None]] = None
        self._route_all: bool = False
        self._grab_ok: bool = False
        self._keyboard_grabbed: bool = False  # holding a persistent XGrabKeyboard

    def prepare(
        self,
        on_key: Callable[[str, str], None],
        should_consume: Callable[[str], bool],
        on_passthrough: Optional[Callable[[str, str], None]] = None,
        on_grabs_changed: Optional[Callable[[Optional[str]], None]] = None,
    ) -> bool:
        """Open the Xlib display and start the event-loop thread.
        Installs zero grabs. Returns True on success, False if Xlib is
        unavailable or the display can't be opened."""
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
        self._on_grabs_changed = on_grabs_changed
        self._stop.clear()
        # Flush any actions that were enqueued after the previous stop() but
        # before this prepare(). Without this, a stale install_grabs() would
        # be picked up by the new thread and silently install grabs on behalf
        # of the previous caller.
        self._actions = _queue.Queue()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="MovementKeyGrabber"
        )
        self._thread.start()
        return True

    def install_grabs(
        self,
        canonical_set: str,
        passthrough_keysyms: Optional[list[str]] = None,
        route_all: bool = False,
    ) -> None:
        """route_all=True (TTR strict, X11 only): grab BOTH keysets,
        GrabModeAsync + owner_events=False, to SUPPRESS native movement
        delivery. Movement is NOT routed from the grabber's own event stream
        (it is lossy under XWayland); the pynput/XRecord feed is the single
        source of truth for movement. Only non-movement keys redirected by the
        active grab are re-delivered via on_passthrough. route_all=False (CC,
        default): legacy conflicting-keyset / GrabModeSync / passthrough +
        on_key routing. Safe from any thread."""
        self._actions.put(("install", canonical_set,
                           list(passthrough_keysyms or []), route_all))

    def uninstall_grabs(self) -> None:
        """Remove all currently-installed passive grabs. Safe to call
        from any thread. No-op if no grabs are installed."""
        self._actions.put(("uninstall",))

    def stop(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            self._actions.put(("uninstall",))
            self._actions.put(("shutdown",))
            self._stop.set()
            self._thread.join(timeout=2.0)
        self._thread = None
        self._cleanup_display()

    def _cleanup_display(self) -> None:
        if self._display is not None:
            if self._keyboard_grabbed:
                try:
                    self._display.ungrab_keyboard(X.CurrentTime)
                except Exception:
                    pass
                self._keyboard_grabbed = False
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
            self._current_canonical = None
            self._route_all = False
            self._grab_ok = False
            self._keyboard_grabbed = False
        # Discard any pending actions so a subsequent prepare() starts with a
        # clean queue. Without this, an install_grabs() enqueued between
        # stop() and the thread's exit would survive into the next lifecycle
        # and silently install grabs the new caller didn't ask for.
        self._actions = _queue.Queue()

    def _conflicting_keysyms(self, canonical_set: str) -> tuple[str, ...]:
        if canonical_set == "wasd":
            return ("Up", "Down", "Left", "Right")
        if canonical_set == "arrows":
            return ("w", "a", "s", "d")
        return ()

    def _install_grabs_inline(self, canonical_set: str,
                              passthrough_keysyms: list[str],
                              route_all: bool = False) -> None:
        if route_all:
            # Persistent whole-keyboard grab for the focused session -- NOT
            # per-key passive grabs. Per-key XGrabKey makes each movement key
            # activate a transient active grab whose teardown (on releasing the
            # activating/first key) churns NotifyGrab/Ungrab focus events that
            # make the focused XWayland TTR (Panda3D) client clear its held-key
            # state, stopping still-held combos. ONE XGrabKeyboard fires a single
            # grab/ungrab (no per-key churn) and keeps the game window focused.
            # All keys redirect here (owner_events=False): movement is routed by
            # the pynput/RECORD feed; non-movement is re-delivered to the focused
            # window via on_passthrough (see _handle_event_route_all). Idempotent
            # on mode so a TTR->TTR focus switch does not re-grab.
            if self._route_all and self._grab_ok:
                self._current_canonical = canonical_set
                return
            self._uninstall_grabs_inline()
            self._route_all = True
            self._grab_ok = False
            # Register the movement keysyms so the handler classifies them as
            # "grabbed" (suppress-only; pynput routes them).
            for keysym_name in _ALL_MOVEMENT_KEYSYMS:
                ks = XK.string_to_keysym(keysym_name)
                if ks == 0:
                    continue
                keycode = self._display.keysym_to_keycode(ks)
                if keycode == 0:
                    continue
                self._keycode_to_name[keycode] = ("grabbed", keysym_name)
            # Pre-map common non-movement keys to their keysym NAMES so the
            # handler can re-deliver them by name. keysym_to_string only resolves
            # printables, so specials (Return/Escape/modifiers/Tab/BackSpace) must
            # be named here. setdefault so a movement entry is never overwritten.
            for keysym_name in passthrough_keysyms:
                ks = XK.string_to_keysym(keysym_name)
                if ks == 0:
                    continue
                keycode = self._display.keysym_to_keycode(ks)
                if keycode == 0:
                    continue
                self._keycode_to_name.setdefault(keycode, ("passthrough", keysym_name))
            # One persistent active keyboard grab. status 0 == GrabSuccess.
            try:
                status = self._root.grab_keyboard(
                    False, X.GrabModeAsync, X.GrabModeAsync, X.CurrentTime)
                self._keyboard_grabbed = (status == X.GrabSuccess)
                if not self._keyboard_grabbed:
                    print(f"[x11_movement_grabber] grab_keyboard not granted (status={status})")
            except Exception as e:  # noqa: BLE001
                print(f"[x11_movement_grabber] grab_keyboard failed: {e}")
                self._keyboard_grabbed = False
            try:
                self._display.sync()
            except Exception:
                pass
            self._grab_ok = self._keyboard_grabbed
            # If the grab was not granted, native is NOT suppressed; report
            # inactive so the router does not synthesize to an unsuppressed window.
            self._current_canonical = canonical_set if self._grab_ok else None
            return
        # ---- legacy CC path (unchanged) ----
        if self._current_canonical == canonical_set and not self._route_all:
            return
        self._uninstall_grabs_inline()
        keysyms = self._conflicting_keysyms(canonical_set)
        for keysym_name in keysyms:
            ks = XK.string_to_keysym(keysym_name)
            if ks == 0:
                continue
            keycode = self._display.keysym_to_keycode(ks)
            if keycode == 0:
                continue
            self._keycode_to_name[keycode] = ("grabbed", keysym_name)
            for mod in _LOCK_MODIFIERS:
                try:
                    self._root.grab_key(keycode, mod, True,
                                        X.GrabModeAsync, X.GrabModeSync)
                    self._grabbed.append((keycode, mod))
                except BadAccess:
                    pass
        for keysym_name in passthrough_keysyms:
            ks = XK.string_to_keysym(keysym_name)
            if ks == 0:
                continue
            keycode = self._display.keysym_to_keycode(ks)
            if keycode == 0:
                continue
            self._keycode_to_name.setdefault(keycode, ("passthrough", keysym_name))
        try:
            self._display.sync()
        except Exception:
            pass
        self._current_canonical = canonical_set

    def _uninstall_grabs_inline(self) -> None:
        # Release the persistent route_all keyboard grab first so the keyboard is
        # never left captured (focus-away / toggle-off / shutdown all route here).
        if self._keyboard_grabbed:
            try:
                self._display.ungrab_keyboard(X.CurrentTime)
            except Exception:
                pass
            self._keyboard_grabbed = False
        for keycode, mod in self._grabbed:
            try:
                self._root.ungrab_key(keycode, mod)
            except Exception:
                pass
        try:
            self._display.sync()
        except Exception:
            pass
        self._grabbed = []
        self._keycode_to_name = {}
        self._current_canonical = None
        self._route_all = False
        self._grab_ok = False

    def _key_physically_down(self, keycode: int) -> bool:
        """True if `keycode` is currently held per the server's physical key
        state (query_keymap). Used to recognize X auto-repeat KeyRelease events
        (the key is still down) so they aren't mistaken for real releases.

        Defensive on purpose: any failure, unexpected shape, or out-of-range
        keycode returns False, so the caller falls back to the same-time-pair
        heuristic and existing behavior is preserved on servers/paths where
        query_keymap is unavailable (and so a raising query_keymap can never
        kill the event-loop thread)."""
        try:
            if keycode < 0 or keycode > 255:
                return False
            km = self._display.query_keymap()
            if not isinstance(km, (list, tuple)) or len(km) != 32:
                return False
            return bool(km[keycode >> 3] & (1 << (keycode & 7)))
        except Exception:
            return False

    def _notify_grabs_changed(self) -> None:
        """Tell the caller (InputService) that grabs ACTUALLY changed, with the
        now-current canonical set (None if uninstalled). Lets the caller gate
        focused-window synthesis on real grab state instead of enqueue time.
        Runs on the worker thread; the callback must be cheap and thread-safe."""
        cb = self._on_grabs_changed
        if cb is None:
            return
        try:
            cb(self._current_canonical)
        except Exception as e:  # noqa: BLE001
            print(f"[x11_movement_grabber] on_grabs_changed raised: {e}")

    def _drain_actions(self) -> bool:
        """Process queued install/uninstall actions. Returns True if a
        shutdown action was seen."""
        try:
            while True:
                action = self._actions.get_nowait()
                try:
                    if action[0] == "install":
                        _, canonical_set, passthrough, route_all = action
                        self._install_grabs_inline(canonical_set, passthrough, route_all)
                        self._notify_grabs_changed()
                    elif action[0] == "uninstall":
                        self._uninstall_grabs_inline()
                        self._notify_grabs_changed()
                    elif action[0] == "shutdown":
                        return True
                except Exception as e:  # noqa: BLE001
                    print(f"[x11_movement_grabber] action {action[0]!r} raised: {e}")
        except _queue.Empty:
            pass
        return False

    def _run(self) -> None:
        try:
            self._run_loop()
        finally:
            # Safety net: never leave the keyboard captured if the worker loop
            # exits unexpectedly (display error, ConnectionClosed, etc.) while a
            # route_all keyboard grab is held. Normal teardown also ungrabs via
            # uninstall / _cleanup_display; this guards the break-out paths.
            if self._keyboard_grabbed and self._display is not None:
                try:
                    self._display.ungrab_keyboard(X.CurrentTime)
                except Exception:
                    pass
                self._keyboard_grabbed = False

    def _run_loop(self) -> None:
        while True:
            if self._drain_actions():
                break
            if self._stop.is_set():
                break
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

            if _ITRACE:
                _ent = self._keycode_to_name.get(event.detail)
                _itrace("grab", f"EVENT {'PRESS' if event.type == X.KeyPress else 'RELEASE'} "
                                f"kc={event.detail} kind={_ent[0] if _ent else None} "
                                f"ks={_ent[1] if _ent else None} canon={self._current_canonical} "
                                f"xtime={event.time}")

            if self._route_all:
                self._handle_event_route_all(event)
                continue
            # ---- legacy KeyRelease guard + _handle_event below (unchanged) ----

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
                # Robust auto-repeat guard. The same-time-pair heuristic below
                # only catches an auto-repeat KeyRelease when its matching
                # KeyPress is the very next queued event. During another key's
                # ACTIVE grab, a held passthrough key's (e.g. the focused toon's
                # WASD) auto-repeat events are redirected here, and the pairing
                # can break (a different key's event interleaves, or the matching
                # press isn't queued yet). A mispaired release used to be sent to
                # the focused window as a real keyup, stopping that toon while the
                # user controlled another toon. If the key is STILL physically
                # held, this release is an auto-repeat artifact -> drop it.
                _down = self._key_physically_down(event.detail)
                if _ITRACE:
                    _itrace("grab", f"RELEASE kc={event.detail} query_keymap_down={_down} "
                                    f"(guard {'DROPS' if _down else 'passes'})")
                if _down:
                    try:
                        self._display.allow_events(X.AsyncKeyboard, event.time)
                        self._display.sync()
                    except Exception:
                        break
                    continue
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
        if _ITRACE:
            _cb = ("on_key" if (consume and self._on_key is not None)
                   else ("on_passthrough" if (kind == "passthrough" and keysym_name
                                              and self._on_passthrough is not None)
                         else "none"))
            _itrace("grab", f"HANDLE kc={event.detail} kind={kind} ks={keysym_name} "
                            f"action={action} consume={consume} "
                            f"allow={'Async' if consume else 'Replay'} cb={_cb}")
        if consume and self._on_key is not None:
            try:
                self._on_key(action, keysym_name)
            except Exception as e:  # noqa: BLE001
                print(f"[x11_movement_grabber] on_key raised: {e}")
        elif kind == "passthrough" and keysym_name and self._on_passthrough is not None:
            # Passthrough keys are not in a passive grab. They reach the
            # grabber only because the active grab activated by a grabbed
            # key redirects all keyboard events here; we hand them to the
            # focused window via the bridge. Grabbed keys with consume=
            # False (e.g. chat is active) are NOT routed here: under
            # GrabModeSync, AllowEvents(ReplayKeyboard) already re-delivers
            # them to the focused window. Calling on_passthrough for that
            # case would double-deliver.
            try:
                self._on_passthrough(action, keysym_name)
            except Exception as e:  # noqa: BLE001
                print(f"[x11_movement_grabber] on_passthrough raised: {e}")

    def _resolve_keysym_name(self, keycode: int) -> Optional[str]:
        """Resolve a keycode to an X keysym NAME string for passthrough re-send.
        Only handles printables (keysym_to_string is ASCII-only); special keys
        (Return/Escape/modifiers/...) are pre-registered by name in
        _keycode_to_name. Returns None if it can't be resolved."""
        try:
            ks = self._display.keycode_to_keysym(keycode, 0)
            if not ks:
                return None
            return XK.keysym_to_string(ks) or None
        except Exception:
            return None

    def _handle_event_route_all(self, event) -> None:
        """route_all (one persistent XGrabKeyboard): EVERY key is redirected here
        (owner_events=False), so native delivery to the focused window is fully
        suppressed. Movement keys are routed to the correct toon by the pynput
        (XRecord) feed -- suppress them here (no-op). EVERY other key is one the
        focused window still needs (chat, Enter, Escape, modifiers, hotkeys); we
        re-deliver it to the focused window via on_passthrough, by its registered
        name or (for unregistered printables) a keysym resolved from the keycode."""
        entry = self._keycode_to_name.get(event.detail)
        if entry is not None and entry[0] == "grabbed":
            return  # movement: suppress here; pynput routes it to its toon
        if self._on_passthrough is None:
            return
        keysym_name = entry[1] if entry is not None else self._resolve_keysym_name(event.detail)
        if not keysym_name:
            return
        action = "keydown" if event.type == X.KeyPress else "keyup"
        try:
            self._on_passthrough(action, keysym_name)
        except Exception as e:  # noqa: BLE001
            print(f"[x11_movement_grabber] on_passthrough raised: {e}")
