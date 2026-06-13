"""
Hotkey Manager — manages the pynput global keyboard listener.
It respects the WindowManager's active window to prevent keylogging
when the user is focused on a different application.
"""

import sys
import queue
import threading
from PySide6.QtCore import QObject, Signal, Qt, QMetaObject, Q_ARG

from utils.key_registry import PYNPUT_NAME_MAP_BASE
from utils.input_trace import trace as _itrace, ENABLED as _ITRACE

keyboard = None


def _keyboard_module():
    global keyboard
    if keyboard is None:
        from pynput import keyboard as pynput_keyboard
        keyboard = pynput_keyboard
    return keyboard

# Build the VK→keysym map at module level so the platform check runs once.
_PYNPUT_VK_MAP = {
    65437: "KP_5",         # KP_Begin (numpad 5 without numlock)
    65421: "KP_Enter",     # KP_Enter

    # X11 Numpad Keysyms (with numlock on)
    65456: "KP_0", 65457: "KP_1", 65458: "KP_2", 65459: "KP_3", 65460: "KP_4",
    65461: "KP_5", 65462: "KP_6", 65463: "KP_7", 65464: "KP_8", 65465: "KP_9",
    65450: "KP_Multiply", 65451: "KP_Add", 65453: "KP_Subtract",
    65454: "KP_Decimal", 65455: "KP_Divide",
}
if sys.platform == "win32":
    # Windows VK codes for numpad — these collide with X11 keysyms for
    # lowercase letters (a=97 … i=105) so they must ONLY be included on Windows.
    _PYNPUT_VK_MAP.update({
        96: "KP_0", 97: "KP_1", 98: "KP_2", 99: "KP_3", 100: "KP_4",
        101: "KP_5", 102: "KP_6", 103: "KP_7", 104: "KP_8", 105: "KP_9",
        106: "KP_Multiply", 107: "KP_Add", 109: "KP_Subtract",
        110: "KP_Decimal", 111: "KP_Divide",
    })


# Windows VK codes for the movement keys the grabber may suppress (both the
# WASD and arrow presets). These are the ONLY keys that ever enter the grabbed
# set, so this small static map is all the win32 event filter needs to translate
# a raw KBDLLHOOKSTRUCT.vkCode into the keysym the InputService router expects.
_WIN32_MOVEMENT_VK = {
    0x57: "w", 0x41: "a", 0x53: "s", 0x44: "d",
    0x26: "Up", 0x28: "Down", 0x25: "Left", 0x27: "Right",
}
# Win32 keyboard messages (incl. the SYS* variants for Alt-combos).
_WM_KEYDOWN, _WM_KEYUP = 0x0100, 0x0101
_WM_SYSKEYDOWN, _WM_SYSKEYUP = 0x0104, 0x0105


def _join_quietly(listener):
    try:
        listener.join(timeout=2.0)
    except Exception:
        pass


class HotkeyManager(QObject):
    profile_load_requested = Signal(int)
    refresh_requested = Signal()

    PYNPUT_VK_MAP = _PYNPUT_VK_MAP
    
    # Derived from key_registry.py — all pynput key.name values across the
    # full registry, including side-agnostic modifier aliases (shift/ctrl/alt).
    PYNPUT_NAME_MAP: dict[str, str] = dict(PYNPUT_NAME_MAP_BASE)

    def __init__(self, window_manager, key_event_queue, suppress_predicate=None):
        super().__init__()
        self.window_manager = window_manager
        self.key_event_queue = key_event_queue
        self.suppress_predicate = suppress_predicate

        self.pressed_keys = set()
        self.listener = None
        self.is_listening = False

        # Known-game-PID set for the darwin target-PID suppression gate. Refreshed
        # on focus changes (NOT on the per-keystroke hot path); empty means the
        # gate is inactive / unknown. Off darwin it stays empty.
        self._darwin_game_pids: frozenset = frozenset()

        # Tracks F5's physical down-state so OS auto-repeat does not re-fire the
        # refresh hotkey. Reset in _stop_listener (a focus-out can stop the
        # listener before the physical release arrives).
        self._f5_down = False

        # We hook into active window changes to start/stop the listener dynamically
        self.window_manager.active_window_changed.connect(self._on_active_window_changed)

    def start(self):
        """Start listening if the current window is an allowed target."""
        if self.is_listening:
            return
        # Trigger an initial check
        self._on_active_window_changed("")

    def stop(self):
        self._stop_listener()

    def _on_active_window_changed(self, active_win_id: str):
        capture = self.window_manager.should_capture_input()
        if sys.platform == "darwin":
            # Refresh the darwin target-PID suppression gate off the hot path:
            # populate it while a game is focused, clear it otherwise so the
            # gate stays inactive when we are not capturing.
            if capture:
                self._refresh_darwin_game_pids()
            else:
                self._darwin_game_pids = frozenset()
        if _ITRACE:
            _itrace("hk_listener", f"active={active_win_id!r} should_capture={capture} "
                                   f"was_listening={self.is_listening} -> "
                                   f"{'START' if capture else 'STOP'}")
        if capture:
            self._start_listener()
        else:
            self._stop_listener()

    def _refresh_darwin_game_pids(self) -> None:
        """Refresh the known-game-PID set used by the darwin target-PID
        suppression gate. Called on focus changes (NOT on the per-keystroke hot
        path). No-op / empty off darwin or on any error."""
        if sys.platform != "darwin":
            return
        try:
            from utils import macos_discovery
            self._darwin_game_pids = frozenset(
                r.pid for r in macos_discovery._enumerate_game_windows()
            )
        except Exception:
            self._darwin_game_pids = frozenset()

    def _start_listener(self):
        if not self.is_listening:
            keyboard_module = _keyboard_module()
            if sys.platform == "win32":
                # Windows suppression goes through the win32 event filter, NOT
                # by returning False from on_press (that raises StopException and
                # KILLS the listener). See _win32_event_filter.
                self.listener = keyboard_module.Listener(
                    on_press=self.on_global_key_press,
                    on_release=self.on_global_key_release,
                    win32_event_filter=self._win32_event_filter,
                )
            elif sys.platform == "darwin":
                self.listener = keyboard_module.Listener(
                    on_press=self.on_global_key_press,
                    on_release=self.on_global_key_release,
                    darwin_intercept=self._darwin_intercept,
                )
            else:
                self.listener = keyboard_module.Listener(
                    on_press=self.on_global_key_press,
                    on_release=self.on_global_key_release,
                )
            self.listener.start()
            self.is_listening = True

    def _win32_event_filter(self, msg, data):
        """pynput win32 event filter — the CORRECT Windows suppression channel.

        Returning False from on_press/on_release does NOT suppress on Windows;
        pynput interprets it as StopException and stops the listener entirely
        (the cause of the "first grabbed key sticks, then no input works" bug).
        The supported mechanism is this filter calling ``suppress_event()``.

        For a grabbed movement key that must be suppressed we enqueue the event
        here (because suppress_event() prevents on_press/on_release from firing)
        and then suppress it at the OS level. Every other key returns True and
        flows through on_press/on_release unchanged, so the listener never stops.
        """
        keysym = None
        do_suppress = False
        try:
            keysym = _WIN32_MOVEMENT_VK.get(getattr(data, "vkCode", None))
            if keysym is None:
                return True  # not a grabbable movement key — normal processing
            sp = self.suppress_predicate
            if sp is None or not sp(keysym):
                return True  # not suppressed right now — on_press/on_release enqueue it
            # Suppressed: enqueue ourselves, mirroring the on_press/on_release
            # capture gating (keydown honours should_capture_input; keyup always
            # enqueues so a held key is never stranded down on a bg toon).
            if msg in (_WM_KEYDOWN, _WM_SYSKEYDOWN):
                if self.window_manager.should_capture_input():
                    try:
                        self.key_event_queue.put(("keydown", keysym), timeout=0.05)
                    except queue.Full:
                        print("[HotkeyManager] queue full, dropping suppressed keydown")
                    do_suppress = True
            elif msg in (_WM_KEYUP, _WM_SYSKEYUP):
                try:
                    self.key_event_queue.put(("keyup", keysym), timeout=0.05)
                except queue.Full:
                    print("[HotkeyManager] queue full, dropping suppressed keyup")
                do_suppress = True
        except Exception as e:  # noqa: BLE001
            if _ITRACE:
                _itrace("hk_filter", f"error msg={msg} err={e}")
            return True
        if do_suppress and self.listener is not None:
            if _ITRACE:
                _itrace("hk_filter", f"suppress msg={msg} keysym={keysym}")
            # Raises SuppressException (NOT an error we catch) → OS-level suppress.
            self.listener.suppress_event()
        return True

    def _quartz_for_intercept(self):
        import Quartz
        return Quartz

    def _darwin_intercept(self, event_type, event):
        """macOS suppression channel (suppress-only; mirrors the Linux model).
        Return None to suppress OS delivery, or the event to pass it through.
        NEVER enqueues — on_global_key_press/on_global_key_release are the single
        enqueue point and fire even for events suppressed here."""
        try:
            Q = self._quartz_for_intercept()
        except Exception:
            return event
        # Tap-health: re-enable a disabled tap so capture does not silently die.
        if event_type in (Q.kCGEventTapDisabledByTimeout,
                          Q.kCGEventTapDisabledByUserInput):
            try:
                tap = getattr(self.listener, "_tap", None)
                if tap is not None:
                    Q.CGEventTapEnable(tap, True)
            except Exception:
                pass
            return event
        from utils import macos_keycodes
        try:
            keycode = Q.CGEventGetIntegerValueField(event, Q.kCGKeyboardEventKeycode)
        except Exception:
            return event
        keysym = macos_keycodes.keysym_for_cgkeycode(keycode)
        if keysym is None:
            return event  # a key we don't translate -> normal processing
        sp = self.suppress_predicate
        if sp is None or not sp(keysym):
            return event  # not suppressed right now
        # Target-PID gate (amendment D): only suppress when the event targets a
        # known game PID. 0/absent target or empty known set -> fall back to the
        # suppress decision (do not over-suppress).
        try:
            target_pid = Q.CGEventGetIntegerValueField(event, Q.kCGEventTargetUnixProcessID)
        except Exception:
            target_pid = 0
        if (self._darwin_game_pids and target_pid
                and int(target_pid) not in self._darwin_game_pids):
            return event  # targets a non-game process -> never eat it
        return None  # suppress OS delivery (on_press/on_release still enqueue)

    def _stop_listener(self):
        if not self.is_listening or not self.listener:
            return
        # _on_active_window_changed runs on the GUI thread via a Qt queued
        # connection from WindowManager's poll thread. listener.join blocks
        # for up to its timeout while pynput's X record session tears down,
        # which freezes the UI on every focus-out. Join in a background
        # thread so the GUI thread is unblocked immediately.
        listener = self.listener
        self.listener = None
        self.is_listening = False
        self.pressed_keys.clear()
        # Deliberate tradeoff: clearing _f5_down here prevents a permanent wedge
        # when F5's physical release is missed because it happened while the
        # listener was stopped (a focus-out). The cost is that F5 held ACROSS a
        # stop+restart can emit one extra refresh on the restarted listener's
        # auto-repeat; that is bounded to one per excursion and coalesced
        # downstream by manual_refresh's cooldown. Avoiding both the wedge and
        # the double-fire would require querying global key state, which pynput
        # does not provide.
        self._f5_down = False
        # Race guard: pynput's _stop_platform reaches for self._display_record
        # which the worker thread sets early in _run(). If stop() is called
        # before that line lands (very fast app launch + close cycle), pynput
        # raises AttributeError. We swallow the known cases so closeEvent's
        # remaining shutdown calls still run.
        try:
            listener.stop()
        except AttributeError:
            pass
        threading.Thread(
            target=lambda: _join_quietly(listener),
            daemon=True,
            name="hotkey-listener-cleanup",
        ).start()

    def normalize_key(self, key):
        # Check vk FIRST for numpad keys: on X11 a numpad key may have both
        # key.char (e.g. '.') and key.vk (e.g. 65454 = KP_Decimal) set.
        # The vk table takes priority so KP_Decimal is not confused with period.
        vk = getattr(key, 'vk', None) or (key if isinstance(key, int) else None)
        if vk is not None:
            mapped = self.PYNPUT_VK_MAP.get(int(vk))
            if mapped is not None:
                return mapped
        if hasattr(key, 'char') and key.char:
            return key.char.lower() if key.char.isalpha() else key.char
        name = getattr(key, 'name', None)
        if name:
            return self.PYNPUT_NAME_MAP.get(name.lower(), None)
        return None

    def on_global_key_press(self, key):
        # Even though we stop the listener, double check capturing rules
        if not self.window_manager.should_capture_input():
            if _ITRACE:
                _itrace("hk_press", f"DROP keydown (should_capture=False) raw={key!r} "
                                    f"active={self.window_manager.active_window_id!r}")
            return None

        normalized = None
        try:
            keyboard_module = _keyboard_module()
            if key in [keyboard_module.Key.ctrl_l, keyboard_module.Key.ctrl_r]:
                self.pressed_keys.add("ctrl")
            elif hasattr(key, 'char') and key.char:
                self.pressed_keys.add(key.char)
                if "ctrl" in self.pressed_keys and key.char in "12345":
                    idx = int(key.char) - 1
                    # Emit signal on the main thread via Qt
                    self.profile_load_requested.emit(idx)

            normalized = self.normalize_key(key)
            if normalized == "F5":
                if not self._f5_down:
                    self._f5_down = True
                    if _ITRACE:
                        _itrace("hk_press", "F5 refresh requested")
                    self.refresh_requested.emit()
                return None  # tool hotkey: never route F5 to the input queue
            if normalized:
                try:
                    self.key_event_queue.put(("keydown", normalized), timeout=0.05)
                    if _ITRACE and normalized in ("Return", "Escape"):
                        _itrace("hk_press", f"ENQUEUE keydown {normalized} "
                                            f"active={self.window_manager.active_window_id!r}")
                except queue.Full:
                    print("[HotkeyManager] Warning: key event queue full after timeout, dropping keydown event.")
        except Exception as e:
            print(f"[HotkeyManager] Keydown handler error: {e}")

        # Suppression is handled by the platform layer, NOT by returning False
        # here: on Windows that stops the listener (use _win32_event_filter); on
        # Linux the X11 passive grab suppresses at the X level. Returning False
        # from a pynput callback ALWAYS stops the listener, so we never do it.
        return None

    def on_global_key_release(self, key):
        normalized = None
        try:
            keyboard_module = _keyboard_module()
            if key in [keyboard_module.Key.ctrl_l, keyboard_module.Key.ctrl_r]:
                self.pressed_keys.discard("ctrl")
            elif hasattr(key, 'char') and key.char:
                self.pressed_keys.discard(key.char)

            normalized = self.normalize_key(key)
            if normalized == "F5":
                # Release always clears _f5_down (no should_capture_input() gate,
                # like the keyup path below): keyups must fire even when capture is
                # off so a held key is never stranded down. Returning here keeps F5
                # out of the input queue, mirroring the press handler.
                self._f5_down = False
                return None
            if normalized:
                try:
                    self.key_event_queue.put(("keyup", normalized), timeout=0.05)
                    if _ITRACE and normalized in ("Return", "Escape"):
                        _itrace("hk_release", f"ENQUEUE keyup {normalized} (no capture gate) "
                                              f"active={self.window_manager.active_window_id!r}")
                except queue.Full:
                    print("[HotkeyManager] Warning: key event queue full after timeout, dropping keyup event.")
        except Exception as e:
            print(f"[HotkeyManager] Keyup handler error: {e}")

        # See on_global_key_press: never return False from a pynput callback
        # (it stops the listener). Suppression is the platform layer's job.
        return None
