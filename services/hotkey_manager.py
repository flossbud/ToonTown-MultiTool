"""
Hotkey Manager — manages the pynput global keyboard listener.
It respects the WindowManager's active window to prevent keylogging
when the user is focused on a different application.
"""

from PySide6.QtCore import QObject, Signal, Qt, QMetaObject, Q_ARG
from pynput import keyboard

class HotkeyManager(QObject):
    profile_load_requested = Signal(int)

    # Numpad keysyms that pynput doesn't resolve to a char
    PYNPUT_VK_MAP = {
        65437: "5",       # KP_Begin (numpad 5)
        65421: "Return",  # KP_Enter
    }
    
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
        if self.is_listening and self.listener:
            self.listener.stop()
            self.listener = None
            self.is_listening = False
            self.pressed_keys.clear()

    def normalize_key(self, key):
        if hasattr(key, 'char') and key.char:
            return key.char.lower() if key.char.isalpha() else key.char
        name = getattr(key, 'name', None)
        if name:
            return self.PYNPUT_NAME_MAP.get(name.lower(), None)
        # Fallback: check raw vk for unresolved numpad keys
        vk = getattr(key, 'vk', None) or (key if isinstance(key, int) else None)
        if vk is not None:
            return self.PYNPUT_VK_MAP.get(int(vk), None)
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
                self.key_event_queue.put(("keydown", normalized))
        except Exception:
            pass

    def on_global_key_release(self, key):
        try:
            if key in [keyboard.Key.ctrl_l, keyboard.Key.ctrl_r]:
                self.pressed_keys.discard("ctrl")
            elif hasattr(key, 'char') and key.char:
                self.pressed_keys.discard(key.char)
                
            normalized = self.normalize_key(key)
            if normalized:
                self.key_event_queue.put(("keyup", normalized))
        except Exception:
            pass
