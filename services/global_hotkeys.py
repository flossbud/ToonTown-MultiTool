"""Always-global app hotkeys via per-chord X11 passive grabs.

The X server delivers ONLY the grabbed chords to this connection, so the
app never sees any other keystroke (stronger privacy than a listener),
and a grabbed chord is CONSUMED - it never reaches the focused window.
Qualifier: while a grabbed chord is physically held, the activated grab
redirects all keyboard events to this connection for the duration of
the hold (matched or ignored, never logged), and stray root-selected
events may arrive; nothing else is ever delivered.
XGrabKey is portal-safe (probed; see the route_all memory). NEVER XTEST.

Structure mirrors utils/x11_movement_grabber.py (the proven in-repo
pattern): own Display, a command queue drained by the event thread, a
select() loop on the display fd with a wakeup pipe, and a defensive
per-event handler that can never kill the thread.

Wayland gap (spec, accepted): grabs fire while any X/XWayland client is
focused; native-Wayland-focused windows do not deliver keys to XWayland.
"""
from __future__ import annotations

import os
import queue
import select
import threading

from PySide6.QtCore import QObject, Signal

from utils.hotkey_chords import parse_chord, x_modmask

try:
    from Xlib import X, XK, display as xdisplay
    from Xlib import error as xerror
    _HAS_XLIB = True
except Exception:                                     # pragma: no cover
    _HAS_XLIB = False


def _lock_combos():
    """Lock-state ignore masks ONLY (Caps=Lock, Num=Mod2, Scroll=Mod5).
    Deliberately NOT x11_movement_grabber._modifier_combos(): that set
    also enumerates user modifiers (right for movement keys), which would
    make a chord fire under EXTRA held modifiers and a bare F-key grab
    swallow Ctrl+F5."""
    if not _HAS_XLIB:
        return ()
    locks = (0, X.LockMask, X.Mod2Mask, X.Mod5Mask)
    combos = set()
    for a in locks:
        for b in locks:
            for c in locks:
                combos.add(a | b | c)
    return tuple(sorted(combos))


_LOCK_COMBOS = _lock_combos()

# The user-modifier portion of an event state we match against.
_USER_MOD_MASK = ((X.ShiftMask | X.ControlMask | X.Mod1Mask | X.Mod4Mask)
                  if _HAS_XLIB else 0)


def _compile_bindings(display, bindings):
    """{action_id: chord-string} -> ({(keycode, exact_user_mask): action_id},
    {action_id: reason}). Unresolvable entries land in failures, never raise."""
    table, failures = {}, {}
    for action_id, chord_text in bindings.items():
        try:
            chord = parse_chord(chord_text)
            keysym = XK.string_to_keysym(chord.key)
            if keysym == 0:
                raise ValueError(f"unknown keysym {chord.key!r}")
            keycode = display.keysym_to_keycode(keysym)
            if not keycode:
                raise ValueError(f"no keycode for {chord.key!r}")
            key = (int(keycode), x_modmask(chord))
            if key in table:
                failures[action_id] = f"duplicate of {table[key]}"
                continue
            table[key] = action_id
        except Exception as e:                        # noqa: BLE001
            failures[action_id] = str(e)
    return table, failures


class GlobalHotkeyProvider(QObject):
    """Seam: platform providers emit action_triggered(action_id) on the
    GUI thread (Qt auto-queues cross-thread signal emissions)."""
    action_triggered = Signal(str)

    def apply_bindings(self, bindings: dict) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError


class X11GlobalHotkeys(GlobalHotkeyProvider):
    def __init__(self, repeat_ok_ids: frozenset = frozenset()):
        super().__init__()
        self._repeat_ok = repeat_ok_ids
        self._display = None
        self._root = None
        self._table = {}          # (keycode, user_mask) -> action_id
        self._grabbed = {}        # same keys, marks server-side grabs
        self._down = set()        # (keycode, user_mask) logically held
        self._failures = {}       # action_id -> reason (for the settings UI)
        self._cmd = queue.Queue()
        self._wake_r, self._wake_w = os.pipe()
        self._thread = None
        self._running = False

    # -- public API (GUI thread) --------------------------------------
    def start(self) -> bool:
        if not _HAS_XLIB:
            self._close_wake_pipe()
            return False
        try:
            self._display = xdisplay.Display()
            self._root = self._display.screen().root
            self._root.change_attributes(event_mask=X.KeyPressMask | X.KeyReleaseMask)
        except Exception:
            try:
                if self._display is not None:
                    self._display.close()
            except Exception:
                pass
            self._display = None
            self._root = None
            self._close_wake_pipe()
            return False
        self._running = True
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="global-hotkeys-x11")
        self._thread.start()
        return True

    def apply_bindings(self, bindings: dict) -> None:
        """Thread-safe: compiled + grabbed on the event thread."""
        self._cmd.put(("apply", dict(bindings)))
        self._wakeup()

    def failures(self) -> dict:
        """action_id -> reason for bindings that could not be armed
        (snapshot; written on the event thread, read on the GUI thread)."""
        return dict(self._failures)

    def stop(self) -> None:
        """Tear down grabs, the display connection, and the wake pipe.
        NOT restartable: create a new provider to re-arm hotkeys."""
        if not self._running:
            return
        self._running = False
        self._wakeup()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _wakeup(self) -> None:
        if self._wake_w == -1:
            return
        try:
            os.write(self._wake_w, b"x")
        except Exception:
            pass

    def _close_wake_pipe(self) -> None:
        """Invalidate the fds BEFORE closing so _wakeup() can never write
        to a closed (and possibly reused) descriptor."""
        for attr in ("_wake_r", "_wake_w"):
            fd = getattr(self, attr)
            setattr(self, attr, -1)
            if fd != -1:
                try:
                    os.close(fd)
                except Exception:
                    pass

    # -- event thread ---------------------------------------------------
    def _run(self) -> None:
        try:
            fd = self._display.fileno()
            while self._running:
                self._drain_commands()
                # Drain events buffered during a rebind BEFORE blocking in
                # select (they are in xlib's queue, not on the socket, so
                # select would sit on them for the full timeout).
                while self._display.pending_events():
                    self._handle_event(self._display.next_event())
                r, _w, _x = select.select([fd, self._wake_r], [], [], 1.0)
                if self._wake_r in r:
                    os.read(self._wake_r, 64)
                while self._display.pending_events():
                    self._handle_event(self._display.next_event())
        except Exception as e:                        # noqa: BLE001
            print(f"[GlobalHotkeys] event loop died: {e}")
        finally:
            self._teardown()

    def _drain_commands(self) -> None:
        while True:
            try:
                kind, payload = self._cmd.get_nowait()
            except queue.Empty:
                return
            if kind == "apply":
                compiled, failures = _compile_bindings(self._display, payload)
                # _apply_compiled mutates this same dict with grab-time
                # refusals, so the stamp below sees BOTH failure kinds.
                self._failures = failures
                self._apply_compiled(compiled)
                self._print_stamp()

    def _print_stamp(self) -> None:
        """Running-code stamp: reports what is ACTUALLY armed (grabbed) and
        every failure, compile-time and grab-time alike - the live-validation
        gate trusts this line, so it must never claim a refused chord."""
        armed = sorted(set(self._grabbed.values()))
        line = "[GlobalHotkeys] armed: " + (", ".join(armed) or "(none)")
        if self._failures:
            line += f"; unavailable: {sorted(self._failures)}"
        print(line)

    def _apply_compiled(self, compiled: dict) -> None:
        """Diff grabs: ungrab removed chords, grab added ones. Per-chord
        BadAccess (another client owns it) is recorded in _failures and
        never tanks the rest."""
        for key in list(self._grabbed):
            if key not in compiled:
                keycode, mask = key
                for lock in _LOCK_COMBOS:
                    try:
                        self._root.ungrab_key(keycode, mask | lock)
                    except Exception:
                        pass
                del self._grabbed[key]
                self._down.discard(key)
        for key, action_id in compiled.items():
            if key in self._grabbed:
                continue
            keycode, mask = key
            catch = xerror.CatchError()   # traps async errors for THESE requests only
            ok = True
            for lock in _LOCK_COMBOS:
                try:
                    self._root.grab_key(keycode, mask | lock, True,
                                        X.GrabModeAsync, X.GrabModeAsync,
                                        onerror=catch)
                except Exception:
                    ok = False
            try:
                self._display.sync()      # forces the async errors to be parsed
            except Exception:
                pass
            err = catch.get_error()
            if err is not None:
                ok = False
            if ok:
                self._grabbed[key] = action_id
            else:
                self._failures[action_id] = (
                    "in use by another application"
                    if err is None or isinstance(err, xerror.BadAccess)
                    else f"grab failed: {err.__class__.__name__}")
                # All-or-nothing: release any lock-combo grabs that DID succeed
                # so a half-armed chord can't silently consume keys.
                for lock in _LOCK_COMBOS:
                    try:
                        self._root.ungrab_key(keycode, mask | lock)
                    except Exception:
                        pass
        self._table = dict(compiled)

    def _handle_event(self, event) -> None:
        try:
            if event.type not in (X.KeyPress, X.KeyRelease):
                return
            key = (int(event.detail), int(event.state) & _USER_MOD_MASK)
            action_id = self._table.get(key)
            if action_id is None:
                return
            if event.type == X.KeyRelease:
                if not self._key_physically_down(int(event.detail)):
                    self._down.discard(key)       # real release, not auto-repeat
                return
            if action_id not in self._repeat_ok:
                if key in self._down:
                    return                        # auto-repeat press: fire once
                self._down.add(key)
            self.action_triggered.emit(action_id)
        except Exception as e:                    # noqa: BLE001
            print(f"[GlobalHotkeys] event handler error: {e}")

    def _key_physically_down(self, keycode: int) -> bool:
        """query_keymap physical-state check (x11_movement_grabber's proven
        auto-repeat-release detector). Any failure returns False (treat as a
        real release: worst case a repeat_ok=False action can fire again)."""
        try:
            if keycode < 0 or keycode > 255:
                return False
            km = self._display.query_keymap()
            if not isinstance(km, (list, tuple)) or len(km) != 32:
                return False
            return bool(km[keycode >> 3] & (1 << (keycode & 7)))
        except Exception:
            return False

    def _teardown(self) -> None:
        try:
            self._apply_compiled({})
        except Exception:
            pass
        try:
            if self._display is not None:
                self._display.close()
        except Exception:
            pass
        self._close_wake_pipe()
