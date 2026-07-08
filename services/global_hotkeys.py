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
    ({(keycode, exact_user_mask): [(action_id, partner_keycode_or_None), ...]},
    {action_id: reason}). Unresolvable entries land in failures, never raise.

    A single-key chord contributes ONE entry (partner None) and OWNS its
    (keycode, mask) slot exclusively. A two-key chord contributes TWO entries,
    one per member key (resolved in sorted order: frozenset iteration order is
    unstable), each carrying the OTHER member's keycode as its partner.

    A member key may be SHARED by several DISTINCT two-key chords - e.g.
    shift+1+t, shift+2+t and shift+3+t all share the 't' member. The slot then
    holds one (action, partner) entry per chord (hence a LIST value), and the
    runtime fires whichever chord's partner is physically held. Only a truly
    identical chord (same keys + mods), or a single-key chord colliding with a
    pair member on the same (keycode, mask) - their grab modes, async vs sync,
    are incompatible - counts as a 'duplicate'. Any refused chord is failed
    WHOLE before anything is inserted, so a chord can never be half-compiled."""
    table, failures = {}, {}
    chord_ids = {}          # (mask, frozenset(keycodes)) -> first action bound to it
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
            if len(entries) < len(keycodes):
                # Both members resolved to ONE keycode (real on some layouts,
                # e.g. KP_1/KP_End): un-armable as a pair, legible refusal.
                failures[action_id] = "chord keys share a keycode"
                continue
            # An IDENTICAL chord (same keys + mods) already bound: a real dup.
            identity = (mask, frozenset(keycodes))
            if identity in chord_ids:
                failures[action_id] = f"duplicate of {chord_ids[identity]}"
                continue
            # Slot compatibility: a single owns its slot exclusively; a pair
            # member may share a slot only with OTHER pair members (distinct
            # partners). Mixing a single with anything on the same (keycode,
            # mask) is un-armable - so is refused, not half-inserted.
            conflict = None
            for key, partner in entries.items():
                existing = table.get(key)
                if not existing:
                    continue
                if partner is None or any(e[1] is None for e in existing):
                    conflict = existing[0][0]
                    break
            if conflict is not None:
                failures[action_id] = f"duplicate of {conflict}"
                continue
            for key, partner in entries.items():
                table.setdefault(key, []).append((action_id, partner))
            chord_ids[identity] = action_id
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
        self._table = {}          # (keycode, user_mask) -> [(action_id, partner_kc|None), ...]
        self._grabbed = {}        # same keys -> [action_id, ...], marks server-side grabs
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
        armed = sorted({a for actions in self._grabbed.values() for a in actions})
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

        compiled: {(keycode, user_mask): [(action_id, partner_keycode|None), ...]}.
        A slot with pair members (partner not None) grabs with
        keyboard_mode=GrabModeSync: the server FREEZES keyboard event
        processing on the activating KeyPress until _handle_event answers with
        AllowEvents, which is what lets the handler decide fire-vs-replay from
        the partner key's physical state. Single-key slots stay GrabModeAsync.
        The grab is issued ONCE per (keycode, mask) no matter how many chords
        share that member key. A key whose REQUIRED MODE changed since the last
        apply is ungrabbed and re-grabbed: a pair member left on a stale async
        grab would silently EAT the key on the partner-up path (async grabs
        consume; only a sync freeze can be replayed).

        Precondition: self._failures holds only THIS apply's compile
        failures (reset by _drain_commands before every call); the
        cascade reads it."""
        # Mutable working copy: a shared-key grab failure prunes every chord
        # that needed that key from ALL its slots without corrupting the input.
        remaining = {key: list(entries) for key, entries in compiled.items()}

        def _needs_sync(entries):
            return bool(entries) and entries[0][1] is not None

        for key in list(self._grabbed):
            entries = remaining.get(key)
            if not entries or (key in self._grab_sync) != _needs_sync(entries):
                self._release_grab(key)
        for key in list(remaining):
            # Drop any chord already failed (compile-time, or a prior slot's
            # grab-failure cascade this apply) before deciding on the grab.
            entries = [e for e in remaining.get(key, []) if e[0] not in self._failures]
            remaining[key] = entries
            if not entries:
                self._release_grab(key)   # nothing live wants this slot
                continue
            if key in self._grabbed:
                # Kept grab: refresh the armed-action list so the stamp stays
                # current (no re-grab; the mode is unchanged by construction).
                self._grabbed[key] = [a for a, _p in entries]
                continue
            keycode, mask = key
            needs_sync = _needs_sync(entries)
            kbd_mode = X.GrabModeSync if needs_sync else X.GrabModeAsync
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
                self._grabbed[key] = [a for a, _p in entries]
                if needs_sync:
                    self._grab_sync.add(key)
            else:
                reason = ("in use by another application"
                          if err is None or isinstance(err, xerror.BadAccess)
                          else f"grab failed: {err.__class__.__name__}")
                # Fail EVERY chord that needed this key and cascade them out of
                # ALL member slots. The cascade releases any slot that thereby
                # empties - including THIS one (all its chords are dead), which
                # also frees any lock-combo grabs that DID succeed before the
                # async error - and keeps a slot still shared by survivors. One
                # dead member must never leave a half-armed chord.
                dead = [a for a, _p in entries]
                for a in dead:
                    self._failures[a] = reason
                self._cascade_remove(dead, remaining)
        self._table = {key: entries for key, entries in remaining.items()
                       if entries and key in self._grabbed}

    def _cascade_remove(self, dead_actions, remaining) -> None:
        """Remove every dead action from all its member slots. A slot that
        loses its last entry is ungrabbed (a pair's surviving members must not
        stay half-armed); a slot still shared by live chords keeps its grab and
        just refreshes its armed-action list."""
        dead = set(dead_actions)
        for key in list(remaining):
            kept = [e for e in remaining[key] if e[0] not in dead]
            if len(kept) == len(remaining[key]):
                continue
            remaining[key] = kept
            if not kept:
                self._release_grab(key)
            elif key in self._grabbed:
                self._grabbed[key] = [a for a, _p in kept]

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
            if not entry:
                if event.type == X.KeyPress:
                    # Rebind-race thaw: grab gone, act as if never grabbed.
                    self._allow_events(X.ReplayKeyboard)
                return
            # A slot is a LIST: one single (partner None), or one-or-more pair
            # members that share this key (each with its own partner).
            is_pair = entry[0][1] is not None
            if event.type == X.KeyRelease:
                # No AllowEvents on releases, ever: after AsyncKeyboard the
                # activated grab continues ASYNC (the terminating release
                # arrives unfrozen); after ReplayKeyboard the grab was
                # released (the release goes to the focus window, not here).
                # Neither path can deliver a frozen release.
                if not self._key_physically_down(int(event.detail)):
                    self._down.discard(key)       # real release, not auto-repeat
                return
            if is_pair:
                # Sync-frozen pair-member press: fire every chord on this key
                # whose PARTNER is physically held, then thaw NO MATTER WHAT.
                mode = X.ReplayKeyboard           # fail-safe default: never eat
                matched = []
                try:
                    for action_id, partner in entry:
                        if self._key_physically_down(partner):
                            matched.append(action_id)
                    if matched:
                        mode = X.AsyncKeyboard    # a partner is held: consume + fire
                finally:
                    self._allow_events(mode)      # cannot raise
                if not matched:
                    return                        # replayed to the focused window
            else:
                # Matched single on an async grab: no-op thaw (covers the
                # pair->single rebind race, where this press was frozen).
                self._allow_events(X.AsyncKeyboard)
                matched = [entry[0][0]]
            # Auto-repeat gating, keyed by the pressed (keycode, mask): fire
            # once per physical hold unless EVERY matched action opted in.
            if any(a not in self._repeat_ok for a in matched):
                if key in self._down:
                    return                        # auto-repeat press: fire once
                self._down.add(key)
            for action_id in matched:
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
        entries = table.get((int(keycode), int(state) & _USER_MOD_MASK))
        if not entries:
            return None
        # A member key may serve several chords (shared 't' in shift+1+t /
        # shift+2+t / ...): return the one whose partner is physically held.
        for action_id, partner in entries:
            if partner is None or is_down(partner):
                return action_id
        return None
    return lookup


# ── macOS: Carbon RegisterEventHotKey provider (CP9-shaped) ──────────────────
# Everything below runs on the GUI thread: InstallEventHandler targets the Qt
# main event loop's dispatcher (GetEventDispatcherTarget), so hotkey events
# arrive inside the running Qt loop and action_triggered emits GUI-side with
# no thread hop. The provider starts NO keyboard listener and never touches
# Text-Input-Source APIs, so the TIS-shim law is untouched (HotkeyManager's
# constructor installs the shim before any pynput listener exists).
#
# CP9 delivery-order law (probed): the app's own CGEventTap PRECEDES Carbon
# dispatch, so a chord whose key the tap suppresses (TTR route_all / CC
# opposite-set grabs) can NEVER arrive here. The caller (main.py) therefore
# flips HotkeyManager into provider mode: fire_hotkeys=False (or every chord
# Carbon CAN see double-fires) + tap-side fallback for exactly what Carbon
# can never see - suppressed chords and two-key chords (RegisterEventHotKey
# is single-key + modifiers).

_CARBON_PATH = "/System/Library/Frameworks/Carbon.framework/Carbon"
_kEventClassKeyboard = 0x6B657962      # 'keyb'
_kEventHotKeyPressed = 5
_kEventHotKeyReleased = 6
_kEventParamDirectObject = 0x2D2D2D2D  # '----'
_typeEventHotKeyID = 0x686B6964        # 'hkid'
_HOTKEY_SIGNATURE = 0x54544D54         # 'TTMT'

# Carbon Events.h modifier masks (NOT CGEventFlags). TTMT canonical mod
# names map: super=Command, alt=Option.
CARBON_MOD_MASKS = {
    "super": 0x0100,   # cmdKey
    "shift": 0x0200,   # shiftKey
    "alt": 0x0800,     # optionKey
    "ctrl": 0x1000,    # controlKey
}


class MacOSCarbonHotkeys(GlobalHotkeyProvider):
    """Carbon twin of X11GlobalHotkeys: system-wide chords via
    RegisterEventHotKey (exact-modifier match, consumed system-wide when
    matched - the X11 passive-grab semantic). Covers the truly-global case
    the scoped pynput path never could (another app focused). Single-key +
    modifier chords only; two-key chords are recorded as failures and stay
    on HotkeyManager's tap-side fallback (scoped to capture)."""

    def __init__(self, repeat_ok_ids: frozenset = frozenset()):
        super().__init__()
        self._repeat_ok = frozenset(repeat_ok_ids)
        self._carbon = None            # ctypes.CDLL once started
        self._target = None            # GetEventDispatcherTarget()
        self._handler_cb = None        # CFUNCTYPE ref (GC anchor - required)
        self._handler_ref = None
        self._refs: list = []          # registered EventHotKeyRefs
        self._id_to_action: dict[int, str] = {}
        self._down_ids: set[int] = set()
        self._failures: dict[str, str] = {}

    # -- public API (GUI thread) --------------------------------------

    def start(self) -> bool:
        import sys
        if sys.platform != "darwin":
            return False
        try:
            import ctypes

            class _EventTypeSpec(ctypes.Structure):
                _fields_ = [("eventClass", ctypes.c_uint32),
                            ("eventKind", ctypes.c_uint32)]

            carbon = ctypes.CDLL(_CARBON_PATH)
            carbon.GetEventDispatcherTarget.restype = ctypes.c_void_p
            carbon.GetEventKind.restype = ctypes.c_uint32
            carbon.GetEventKind.argtypes = [ctypes.c_void_p]
            target = carbon.GetEventDispatcherTarget()
            if not target:
                print("[GlobalHotkeys] Carbon: no dispatcher target")
                return False
            handler_type = ctypes.CFUNCTYPE(
                ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p,
                ctypes.c_void_p)
            self._handler_cb = handler_type(self._carbon_event)
            specs = (_EventTypeSpec * 2)(
                _EventTypeSpec(_kEventClassKeyboard, _kEventHotKeyPressed),
                _EventTypeSpec(_kEventClassKeyboard, _kEventHotKeyReleased))
            handler_ref = ctypes.c_void_p()
            err = carbon.InstallEventHandler(
                ctypes.c_void_p(target), self._handler_cb, 2, specs, None,
                ctypes.byref(handler_ref))
            if err != 0:
                print(f"[GlobalHotkeys] Carbon: InstallEventHandler err={err}")
                self._handler_cb = None
                return False
            self._carbon = carbon
            self._target = target
            self._handler_ref = handler_ref
            return True
        except Exception as e:                        # noqa: BLE001
            print(f"[GlobalHotkeys] Carbon provider unavailable: {e}")
            self._handler_cb = None
            return False

    def apply_bindings(self, bindings: dict) -> None:
        """(Re)register every bound chord; previous registrations are
        dropped first so a rebind never leaves a stale chord armed. GUI
        thread only (Carbon target lives on the main loop)."""
        if self._carbon is None:
            return
        import ctypes
        from utils.hotkey_chords import parse_chord
        from utils.macos_keycodes import cgkeycode_for_keysym

        self._unregister_all()
        failures: dict[str, str] = {}
        seen: dict[tuple[int, int], str] = {}
        next_id = 1
        for action_id in sorted(bindings):
            chord_text = bindings[action_id]
            try:
                chord = parse_chord(chord_text)
            except Exception as e:                    # noqa: BLE001
                failures[action_id] = str(e)
                continue
            if len(chord.keys) > 1:
                # RegisterEventHotKey is single-key+modifiers; the tap-side
                # fallback still fires these while a game window or the app
                # is focused (capture scope) - global reach is what's lost.
                failures[action_id] = ("two-key chord: works while a game "
                                       "or this app is focused (no global "
                                       "reach on macOS)")
                continue
            keysym = chord.key
            vk = cgkeycode_for_keysym(keysym)
            if vk is None:
                failures[action_id] = f"no macOS keycode for {keysym!r}"
                continue
            mods = 0
            for m in chord.mods:
                mods |= CARBON_MOD_MASKS.get(m, 0)
            if (vk, mods) in seen:
                failures[action_id] = f"duplicate of {seen[(vk, mods)]}"
                continue
            class _EventHotKeyID(ctypes.Structure):
                _fields_ = [("signature", ctypes.c_uint32),
                            ("id", ctypes.c_uint32)]
            hk_id = _EventHotKeyID(_HOTKEY_SIGNATURE, next_id)
            ref = ctypes.c_void_p()
            err = self._carbon.RegisterEventHotKey(
                vk, mods, hk_id, ctypes.c_void_p(self._target), 0,
                ctypes.byref(ref))
            if err != 0:
                failures[action_id] = f"RegisterEventHotKey err={err}"
                continue
            seen[(vk, mods)] = action_id
            self._refs.append(ref)
            self._id_to_action[next_id] = action_id
            next_id += 1
        self._failures = failures
        self._print_stamp()

    def failures(self) -> dict:
        """action_id -> reason for bindings that could not be armed
        globally (feeds the Settings hotkeys-card badges, X11 parity)."""
        return dict(self._failures)

    def stop(self) -> None:
        """Unregister every chord and remove the Carbon handler. NOT
        restartable: create a new provider to re-arm."""
        self._unregister_all()
        if self._carbon is not None and self._handler_ref is not None:
            try:
                self._carbon.RemoveEventHandler(self._handler_ref)
            except Exception:                          # noqa: BLE001
                pass
        self._carbon = None
        self._target = None
        self._handler_ref = None
        self._handler_cb = None

    # -- Carbon event path (GUI thread: the dispatcher IS the Qt loop) --

    def _carbon_event(self, _call_ref, event_ref, _user_data) -> int:
        """ctypes shell: extract (kind, hotkey id) and hand off. Must never
        raise into Carbon; always returns noErr (the hotkey event is ours -
        RegisterEventHotKey already consumed the keystroke system-wide)."""
        try:
            import ctypes

            class _EventHotKeyID(ctypes.Structure):
                _fields_ = [("signature", ctypes.c_uint32),
                            ("id", ctypes.c_uint32)]

            kind = int(self._carbon.GetEventKind(ctypes.c_void_p(event_ref)))
            hk = _EventHotKeyID()
            err = self._carbon.GetEventParameter(
                ctypes.c_void_p(event_ref),
                ctypes.c_uint32(_kEventParamDirectObject),
                ctypes.c_uint32(_typeEventHotKeyID),
                None, ctypes.sizeof(hk), None, ctypes.byref(hk))
            if err == 0 and int(hk.signature) == _HOTKEY_SIGNATURE:
                self._dispatch(kind, int(hk.id))
        except Exception:                              # noqa: BLE001
            pass
        return 0

    def _dispatch(self, kind: int, hk_id: int) -> None:
        """Pure dispatch (unit-testable): pressed fires the action once per
        physical press; a repeated pressed without an intervening released
        is OS auto-repeat and re-fires only repeat_ok actions (X11 parity)."""
        action_id = self._id_to_action.get(hk_id)
        if action_id is None:
            return
        if kind == _kEventHotKeyPressed:
            repeat = hk_id in self._down_ids
            self._down_ids.add(hk_id)
            if not repeat or action_id in self._repeat_ok:
                self.action_triggered.emit(action_id)
        elif kind == _kEventHotKeyReleased:
            self._down_ids.discard(hk_id)

    # -- internals ------------------------------------------------------

    def _unregister_all(self) -> None:
        if self._carbon is not None:
            for ref in self._refs:
                try:
                    self._carbon.UnregisterEventHotKey(ref)
                except Exception:                      # noqa: BLE001
                    pass
        self._refs = []
        self._id_to_action = {}
        self._down_ids = set()

    def _print_stamp(self) -> None:
        """Running-code stamp (live validation starts by confirming it):
        reports what is ACTUALLY registered with Carbon plus every refusal,
        matching the X11 stamp shape."""
        armed = sorted(self._id_to_action.values())
        line = ("[GlobalHotkeys] armed (carbon): "
                + (", ".join(armed) or "(none)"))
        if self._failures:
            line += f"; unavailable: {sorted(self._failures)}"
        print(line)
