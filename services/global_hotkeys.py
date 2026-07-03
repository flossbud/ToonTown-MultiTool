"""Always-global app hotkeys via per-chord X11 passive grabs.

The X server delivers ONLY the grabbed chords to this connection, so the
app never sees any other keystroke (stronger privacy than a listener),
and a grabbed chord is CONSUMED - it never reaches the focused window.
Qualifier: while a grabbed chord is physically held, the activated grab
redirects all keyboard events to this connection for the duration of
the hold (matched or ignored, never logged), and stray root-selected
events may arrive; nothing else is ever delivered.
XGrabKey is portal-safe (probed; see the route_all memory). NEVER XTEST.

Two-key chords (e.g. shift+1+t): the server cannot grab a two-KEY
combination, so EACH member key is grabbed with keyboard_mode=
GrabModeSync. The activating KeyPress freezes keyboard event processing
until this client answers with AllowEvents: partner key physically held
(query_keymap) -> AsyncKeyboard (consume + fire; the grab continues
async until release), partner up -> ReplayKeyboard (the event replays
to the focused window as if never grabbed - shift+t alone still types
into the game). See _handle_event's freeze-safety invariant.

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
    """{action_id: chord-string} ->
    ({(keycode, exact_user_mask): (action_id, partner_keycode_or_None)},
    {action_id: reason}). Unresolvable entries land in failures, never raise.

    A single-key chord contributes ONE entry with partner None. A two-key
    chord contributes TWO entries, one per member key (resolved in sorted
    order: frozenset iteration order is unstable), each carrying the OTHER
    member's keycode as its partner. Any (keycode, mask) collision - across
    actions or between a pair's own members - fails the WHOLE action before
    anything is inserted, so a chord can never be half-compiled."""
    table, failures = {}, {}
    for action_id, chord_text in bindings.items():
        try:
            chord = parse_chord(chord_text)
            keycodes = []
            for key_name in sorted(chord.keys):
                keysym = XK.string_to_keysym(key_name)
                if keysym == 0:
                    raise ValueError(f"unknown keysym {key_name!r}")
                keycode = display.keysym_to_keycode(keysym)
                if not keycode:
                    raise ValueError(f"no keycode for {key_name!r}")
                keycodes.append(int(keycode))
            mask = x_modmask(chord)
            if len(keycodes) == 1:
                entries = {(keycodes[0], mask): None}
            else:
                kc_a, kc_b = keycodes
                entries = {(kc_a, mask): kc_b, (kc_b, mask): kc_a}
            dup = next((key for key in entries if key in table), None)
            if dup is not None or len(entries) < len(keycodes):
                owner = table[dup][0] if dup is not None else action_id
                failures[action_id] = f"duplicate of {owner}"
                continue
            for key, partner in entries.items():
                table[key] = (action_id, partner)
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
        self._table = {}          # (keycode, user_mask) -> (action_id, partner_kc|None)
        self._grabbed = {}        # same keys -> action_id, marks server-side grabs
        self._grab_sync = set()   # keys grabbed keyboard_mode=GrabModeSync (pair members)
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

    def _release_grab(self, key) -> None:
        """Ungrab every lock-combo variant of *key* and drop all local state
        for it. Safe on keys that were never grabbed."""
        keycode, mask = key
        for lock in _LOCK_COMBOS:
            try:
                self._root.ungrab_key(keycode, mask | lock)
            except Exception:
                pass
        self._grabbed.pop(key, None)
        self._grab_sync.discard(key)
        self._down.discard(key)

    def _apply_compiled(self, compiled: dict) -> None:
        """Diff grabs: ungrab removed chords, grab added ones. Per-chord
        BadAccess (another client owns it) is recorded in _failures and
        never tanks the rest.

        compiled: {(keycode, user_mask): (action_id, partner_keycode|None)}.
        Pair members (partner not None) grab with keyboard_mode=GrabModeSync:
        the server FREEZES keyboard event processing on the activating
        KeyPress until _handle_event answers with AllowEvents, which is what
        lets the handler decide fire-vs-replay from the partner key's
        physical state. Singles stay GrabModeAsync (today's behavior). A key
        whose REQUIRED MODE changed since the last apply is ungrabbed and
        re-grabbed: a pair member left on a stale async grab would silently
        EAT the key on the partner-up path (async grabs consume; only a
        sync freeze can be replayed)."""
        for key in list(self._grabbed):
            entry = compiled.get(key)
            needs_sync = entry is not None and entry[1] is not None
            if entry is None or (key in self._grab_sync) != needs_sync:
                self._release_grab(key)
        for key, (action_id, partner) in compiled.items():
            if action_id in self._failures:
                # A pair whose OTHER member already failed this apply: never
                # half-arm - release this member too if an earlier apply (or
                # this one) had grabbed it, and record the failure only once.
                self._release_grab(key)
                continue
            if key in self._grabbed:
                self._grabbed[key] = action_id   # keep the stamp's action current
                continue
            keycode, mask = key
            kbd_mode = X.GrabModeSync if partner is not None else X.GrabModeAsync
            catch = xerror.CatchError()   # traps async errors for THESE requests only
            ok = True
            for lock in _LOCK_COMBOS:
                try:
                    self._root.grab_key(keycode, mask | lock, True,
                                        X.GrabModeAsync, kbd_mode,
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
                if partner is not None:
                    self._grab_sync.add(key)
            else:
                self._failures[action_id] = (
                    "in use by another application"
                    if err is None or isinstance(err, xerror.BadAccess)
                    else f"grab failed: {err.__class__.__name__}")
                # All-or-nothing: release any lock-combo grabs that DID succeed
                # so a half-armed chord can't silently consume keys...
                self._release_grab(key)
                # ...and for a PAIR, cascade to the other member (whether it
                # was grabbed earlier in this loop or kept from a previous
                # apply): one dead member must never leave a half-armed chord.
                if partner is not None:
                    partner_key = (partner, mask)
                    if self._grabbed.get(partner_key) == action_id:
                        self._release_grab(partner_key)
        self._table = dict(compiled)

    def _allow_events(self, mode) -> None:
        """AllowEvents(mode) + flush. NEVER raises. The sync() matters: xlib
        BUFFERS requests, and an AllowEvents sitting in the output buffer
        thaws nothing (the in-repo precedent, x11_movement_grabber, flushes
        the same way). Per the X protocol, AllowEvents is a no-op when the
        device is not frozen by this client, so over-calling is safe."""
        try:
            self._display.allow_events(mode, X.CurrentTime)
            self._display.sync()
        except Exception:
            pass

    def _handle_event(self, event) -> None:
        """FREEZE-SAFETY INVARIANT: every KeyPress that MAY be sync-frozen
        (any pair-member grab is keyboard_mode=GrabModeSync) must reach an
        AllowEvents on every path, or the user's keyboard freezes
        SYSTEM-WIDE until this client dies. Hence: nothing that can raise
        sits between event receipt and the thaw; the partner check runs
        inside try/finally with fail-safe ReplayKeyboard; and unmatched or
        partner-less presses thaw defensively (a rebind can remove/retype a
        grab while its frozen KeyPress is already in flight - UngrabKey does
        not thaw an ACTIVE grab's freeze). AllowEvents is a no-op when
        nothing is frozen, so the defensive calls cost one round-trip and
        change nothing on the normal async paths."""
        try:
            if event.type not in (X.KeyPress, X.KeyRelease):
                return
            key = (int(event.detail), int(event.state) & _USER_MOD_MASK)
            entry = self._table.get(key)
            if entry is None:
                if event.type == X.KeyPress:
                    # Rebind-race thaw: grab gone, act as if never grabbed.
                    self._allow_events(X.ReplayKeyboard)
                return
            action_id, partner = entry
            if event.type == X.KeyRelease:
                # No AllowEvents on releases, ever: after AsyncKeyboard the
                # activated grab continues ASYNC (the terminating release
                # arrives unfrozen); after ReplayKeyboard the grab was
                # released (the release goes to the focus window, not here).
                # Neither path can deliver a frozen release.
                if not self._key_physically_down(int(event.detail)):
                    self._down.discard(key)       # real release, not auto-repeat
                return
            if partner is not None:
                # Sync-frozen pair-member press: decide fire-vs-replay from
                # the PARTNER key's physical state, then thaw NO MATTER WHAT.
                mode = X.ReplayKeyboard           # fail-safe default: never eat
                try:
                    if self._key_physically_down(partner):
                        mode = X.AsyncKeyboard    # both held: consume + fire
                finally:
                    self._allow_events(mode)      # cannot raise
                if mode != X.AsyncKeyboard:
                    return                        # replayed to the focused window
            else:
                # Matched single on an async grab: no-op thaw (covers the
                # pair->single rebind race, where this press was frozen).
                self._allow_events(X.AsyncKeyboard)
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


def make_event_lookup(display_like, settings_manager):
    """Build lookup(keycode, state, is_down) -> action_id|None from the
    CURRENT effective bindings, resolving keycodes via *display_like* (any
    object with keysym_to_keycode). is_down(keycode)->bool is supplied by
    the caller (route_all's query_keymap physical check): a pair member
    matches only while its PARTNER key is physically held; otherwise the
    press returns None and falls through to normal routing. No replay
    semantics are needed there - route_all's XGrabKeyboard is an active
    async grab that swallows everything, and delivery is the pynput feed's
    job. The caller rebuilds the lookup on settings change."""
    from utils.hotkey_actions import effective_bindings
    table, _failures = _compile_bindings(
        display_like, effective_bindings(settings_manager))

    def lookup(keycode, state, is_down):
        entry = table.get((int(keycode), int(state) & _USER_MOD_MASK))
        if entry is None:
            return None
        action_id, partner = entry
        if partner is not None and not is_down(partner):
            return None
        return action_id
    return lookup
