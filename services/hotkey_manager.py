"""
Hotkey Manager — manages the pynput global keyboard listener.
It respects the WindowManager's active window to prevent keylogging
when the user is focused on a different application.
"""

import sys
import queue
import threading
from PySide6.QtCore import QObject, Signal, Qt, QMetaObject, Q_ARG
from pynput import keyboard

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


def _join_quietly(listener):
    try:
        listener.join(timeout=2.0)
    except Exception:
        pass


class HotkeyManager(QObject):
    profile_load_requested = Signal(int)

    PYNPUT_VK_MAP = _PYNPUT_VK_MAP
    
    PYNPUT_NAME_MAP = {
        "space": "space", "enter": "Return", "esc": "Escape",
        "backspace": "BackSpace", "tab": "Tab", "delete": "Delete",
        "up": "Up", "down": "Down", "left": "Left", "right": "Right",
        "shift": "Shift_L", "shift_l": "Shift_L", "shift_r": "Shift_R",
        "ctrl": "Control_L", "ctrl_l": "Control_L", "ctrl_r": "Control_R",
        "alt": "Alt_L", "alt_l": "Alt_L", "alt_r": "Alt_R",
    }

    def __init__(self, window_manager, key_event_queue):
        super().__init__()
        self.window_manager = window_manager
        self.key_event_queue = key_event_queue
        
        self.pressed_keys = set()
        self.listener = None
        self.is_listening = False
        
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
        if self.window_manager.should_capture_input():
            self._start_listener()
        else:
            self._stop_listener()

    def _start_listener(self):
        if not self.is_listening:
            self.listener = keyboard.Listener(
                on_press=self.on_global_key_press,
                on_release=self.on_global_key_release
            )
            self.listener.start()
            self.is_listening = True

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
        listener.stop()
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
            return
            
        try:
            if key in [keyboard.Key.ctrl_l, keyboard.Key.ctrl_r]:
                self.pressed_keys.add("ctrl")
            elif hasattr(key, 'char') and key.char:
                self.pressed_keys.add(key.char)
                if "ctrl" in self.pressed_keys and key.char in "12345":
                    idx = int(key.char) - 1
                    # Emit signal on the main thread via Qt
                    self.profile_load_requested.emit(idx)
                    
            normalized = self.normalize_key(key)
            if normalized:
                try:
                    self.key_event_queue.put(("keydown", normalized), timeout=0.05)
                except queue.Full:
                    print("[HotkeyManager] Warning: key event queue full after timeout, dropping keydown event.")
        except Exception as e:
            print(f"[HotkeyManager] Keydown handler error: {e}")

    def on_global_key_release(self, key):
        try:
            if key in [keyboard.Key.ctrl_l, keyboard.Key.ctrl_r]:
                self.pressed_keys.discard("ctrl")
            elif hasattr(key, 'char') and key.char:
                self.pressed_keys.discard(key.char)
                
            normalized = self.normalize_key(key)
            if normalized:
                try:
                    self.key_event_queue.put(("keyup", normalized), timeout=0.05)
                except queue.Full:
                    print("[HotkeyManager] Warning: key event queue full after timeout, dropping keyup event.")
        except Exception as e:
            print(f"[HotkeyManager] Keyup handler error: {e}")
