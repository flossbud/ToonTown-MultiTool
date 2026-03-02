import queue
import subprocess
import threading
import time
from PySide6.QtCore import QObject, Signal

WASD_KEYS     = frozenset({'w', 'a', 's', 'd'})
MOVEMENT_KEYS = WASD_KEYS | frozenset({'Up', 'Down', 'Left', 'Right', 'space'})
ARROW_KEYS    = frozenset({'Up', 'Down', 'Left', 'Right'})
ARROW_TO_WASD = {'Up': 'w', 'Down': 's', 'Left': 'a', 'Right': 'd'}

MODIFIER_KEYS = frozenset({'Shift_L', 'Shift_R', 'Control_L', 'Control_R', 'Alt_L', 'Alt_R'})
MODIFIER_PREFIX = {
    'Shift_L': 'shift', 'Shift_R': 'shift',
    'Control_L': 'ctrl', 'Control_R': 'ctrl',
    'Alt_L': 'alt', 'Alt_R': 'alt',
}

NAMED_KEYSYMS = {
    'space':     'space',
    'Return':    'Return',
    'BackSpace': 'BackSpace',
    'Tab':       'Tab',
    'Escape':    'Escape',
    'Delete':    'Delete',
    'Up':        'Up',
    'Down':      'Down',
    'Left':      'Left',
    'Right':     'Right',
    'Shift_L':   'Shift_L',
    'Shift_R':   'Shift_R',
    'Control_L': 'Control_L',
    'Control_R': 'Control_R',
    'Alt_L':     'Alt_L',
    'Alt_R':     'Alt_R',
}

CHAR_TO_PHYSICAL_KEYSYM = {
    **{c: c for c in 'abcdefghijklmnopqrstuvwxyz'},
    **{c: c for c in '0123456789'},
    '-': 'minus',        '=': 'equal',
    '[': 'bracketleft',  ']': 'bracketright',
    '\\': 'backslash',   ';': 'semicolon',
    "'": 'apostrophe',   ',': 'comma',
    '.': 'period',       '/': 'slash',
    '`': 'grave',
    '!': '1',  '@': '2',  '#': '3',  '$': '4',  '%': '5',
    '^': '6',  '&': '7',  '*': '8',  '(': '9',  ')': '0',
    '_': 'minus',        '+': 'equal',
    '{': 'bracketleft',  '}': 'bracketright',
    '|': 'backslash',    ':': 'semicolon',
    '"': 'apostrophe',   '<': 'comma',
    '>': 'period',       '?': 'slash',
    '~': 'grave',
}


class ActiveWindowCache:
    POLL_INTERVAL = 0.1

    def __init__(self):
        self._active_id = None
        self._lock = threading.Lock()
        self._running = False
        self._thread = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _poll_loop(self):
        while self._running:
            try:
                result = subprocess.check_output(
                    ["xdotool", "getactivewindow"],
                    stderr=subprocess.DEVNULL
                ).decode().strip()
                with self._lock:
                    self._active_id = result
            except Exception:
                with self._lock:
                    self._active_id = None
            time.sleep(self.POLL_INTERVAL)

    def get(self):
        with self._lock:
            return self._active_id


class InputService(QObject):
    log_signal = Signal(str)
    window_ids_updated = Signal(list)

    BACKSPACE_REPEAT_DELAY    = 0.4
    BACKSPACE_REPEAT_INTERVAL = 0.05

    def __init__(self, get_enabled_toons, get_movement_modes, get_event_queue_func, get_chat_enabled=None, settings_manager=None):
        super().__init__()
        self.get_enabled_toons = get_enabled_toons
        self.get_movement_modes = get_movement_modes
        self.get_event_queue = get_event_queue_func
        self.get_chat_enabled = get_chat_enabled
        self.settings_manager = settings_manager
        self.running = False
        self.thread = None
        self.window_ids = []

        self.keys_held = set()
        self.bg_typing_held = set()
        self.modifiers_held = set()
        self.chat_active = set()

        self._window_cache = ActiveWindowCache()
        self._xlib = None

    def start(self):
        self._apply_backend_setting()
        self.running = True
        self._window_cache.start()
        self.assign_windows()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def _apply_backend_setting(self):
        """Connect or disconnect Xlib based on current settings."""
        use_xlib = (self.settings_manager.get("input_backend", "xlib") == "xlib") if self.settings_manager else True
        if use_xlib and self._xlib is None:
            try:
                from utils.xlib_backend import XlibBackend
                self._xlib = XlibBackend()
                self._xlib.connect()
            except Exception as e:
                print(f"[InputService] Xlib backend unavailable, falling back to xdotool: {e}")
                self._xlib = None
        elif not use_xlib and self._xlib is not None:
            self._xlib.disconnect()
            self._xlib = None

    def stop(self):
        self.running = False
        self._window_cache.stop()
        self.release_all_keys()

    def shutdown(self):
        """Call once on app exit to clean up the Xlib connection."""
        self.stop()
        if self._xlib:
            self._xlib.disconnect()
            self._xlib = None

    def assign_windows(self):
        try:
            raw_ids = subprocess.check_output(
                ["xdotool", "search", "--class", "Toontown Rewritten"],
                stderr=subprocess.DEVNULL
            ).decode().strip().split("\n")

            visible_ids = []
            for wid in (w.strip() for w in raw_ids if w.strip()):
                try:
                    geo = subprocess.check_output(
                        ["xdotool", "getwindowgeometry", wid],
                        stderr=subprocess.DEVNULL
                    ).decode()
                    if "Position:" in geo and "Geometry:" in geo:
                        visible_ids.append(wid)
                except subprocess.CalledProcessError:
                    continue

            # Always sort left to right by window X position
            def get_x(win_id):
                try:
                    for line in subprocess.check_output(
                        ["xdotool", "getwindowgeometry", win_id],
                        stderr=subprocess.DEVNULL
                    ).decode().splitlines():
                        if "Position:" in line:
                            return int(line.split()[1].split(",")[0])
                except Exception:
                    return 99999
            visible_ids.sort(key=get_x)

            self.window_ids = list(dict.fromkeys(visible_ids))[:4]

        except subprocess.CalledProcessError:
            self.window_ids = []

        self.window_ids_updated.emit(self.window_ids)

    def run(self):
        event_queue    = self.get_event_queue()
        bs_press_time  = None
        bs_last_repeat = 0.0

        while self.running:
            if not self.should_send_input():
                while not event_queue.empty():
                    try:
                        event_queue.get_nowait()
                    except queue.Empty:
                        break
                if self.keys_held or self.modifiers_held:
                    enabled = self.get_enabled_toons()
                    modes   = self.get_movement_modes()
                    for key in list(self.keys_held):
                        self._release_movement_key(key, enabled, modes)
                    for key in list(self.modifiers_held):
                        self._send_modifier_to_bg("keyup", key, enabled, modes)
                    self.keys_held.clear()
                    self.modifiers_held.clear()
                self.bg_typing_held.clear()
                bs_press_time  = None
                bs_last_repeat = 0.0
                time.sleep(0.01)
                continue

            now     = time.monotonic()
            enabled = self.get_enabled_toons()
            modes   = self.get_movement_modes()

            if not self.window_ids:
                self.assign_windows()

            while not event_queue.empty():
                try:
                    action, key = event_queue.get_nowait()
                except queue.Empty:
                    break

                if action == "keydown":

                    if key in MODIFIER_KEYS:
                        if key not in self.modifiers_held:
                            self.modifiers_held.add(key)
                            self._send_modifier_to_bg("keydown", key, enabled, modes)

                    elif key in MOVEMENT_KEYS:
                        if key not in self.keys_held:
                            self.keys_held.add(key)
                            self._send_movement_key("keydown", key, enabled, modes)
                            if key in WASD_KEYS and self.chat_active:
                                self._send_typing_to_bg(key, enabled, modes)

                    elif key == "BackSpace":
                        if key not in self.keys_held:
                            self.keys_held.add(key)
                            bs_press_time  = now
                            bs_last_repeat = 0.0
                            self._send_movement_key("keydown", key, enabled, modes)

                    elif key == "Return":
                        if key not in self.bg_typing_held:
                            self.bg_typing_held.add(key)
                            for i, mode in enumerate(modes):
                                if mode == "ARROWS" and i < len(self.window_ids) and enabled[i]:
                                    if not self._is_chat_allowed(i):
                                        pass
                                    elif i in self.chat_active:
                                        self.chat_active.discard(i)
                                    else:
                                        self.chat_active.add(i)
                            self._send_typing_to_bg(key, enabled, modes)

                    elif key == "Escape":
                        if key not in self.bg_typing_held:
                            self.bg_typing_held.add(key)
                            for i, mode in enumerate(modes):
                                if mode == "ARROWS" and i < len(self.window_ids) and enabled[i]:
                                    self.chat_active.discard(i)
                            self._send_typing_to_bg(key, enabled, modes)

                    else:
                        if key not in self.bg_typing_held:
                            self.bg_typing_held.add(key)
                            self._send_typing_to_bg(key, enabled, modes)

                elif action == "keyup":

                    if key in MODIFIER_KEYS:
                        self.modifiers_held.discard(key)
                        self._send_modifier_to_bg("keyup", key, enabled, modes)

                    elif key in self.keys_held:
                        self.keys_held.discard(key)
                        if key == "BackSpace":
                            bs_press_time  = None
                            bs_last_repeat = 0.0
                        self._release_movement_key(key, enabled, modes)

                    else:
                        self.bg_typing_held.discard(key)

            if bs_press_time is not None and "BackSpace" in self.keys_held:
                held_for = now - bs_press_time
                if held_for >= self.BACKSPACE_REPEAT_DELAY:
                    if now - bs_last_repeat >= self.BACKSPACE_REPEAT_INTERVAL:
                        bs_last_repeat = now
                        self._send_backspace_to_background(enabled, modes)

            time.sleep(0.005)

    def should_send_input(self):
        active = self._window_cache.get()
        if not active:
            return False
        if active in self.window_ids:
            return True
        multitool_id = self.settings_manager.get("multitool_window_id") if self.settings_manager else None
        return bool(multitool_id and active == str(multitool_id))

    def _active_modifiers(self):
        seen = set()
        mods = []
        for key in self.modifiers_held:
            prefix = MODIFIER_PREFIX.get(key)
            if prefix and prefix not in seen:
                seen.add(prefix)
                mods.append(prefix)
        return mods

    def _is_chat_allowed(self, toon_index):
        if self.get_chat_enabled is None:
            return True
        chat_enabled = self.get_chat_enabled()
        return toon_index < len(chat_enabled) and chat_enabled[toon_index]

    def _is_chat_active(self, toon_index):
        return toon_index in self.chat_active

    def _send_modifier_to_bg(self, action, key, enabled, modes):
        active_window = self._window_cache.get()
        keysym = self._resolve_keysym(key)
        if not keysym:
            return
        for i, (is_enabled, mode) in enumerate(zip(enabled, modes)):
            if not is_enabled or i >= len(self.window_ids):
                continue
            win = self.window_ids[i]
            if win != active_window:
                self._send_via_backend(action, win, keysym)

    def _send_typing_to_bg(self, key, enabled, modes):
        active_window = self._window_cache.get()

        for i, (is_enabled, mode) in enumerate(zip(enabled, modes)):
            if not is_enabled or i >= len(self.window_ids):
                continue
            if mode == "ARROWS" and key in WASD_KEYS and not self._is_chat_active(i):
                continue
            if mode == "WASD" and key in ARROW_KEYS:
                continue
            if key in ("Return", "Escape") and not self._is_chat_allowed(i):
                continue

            win = self.window_ids[i]
            if win == active_window:
                continue

            keysym = self._resolve_keysym(key)
            if not keysym:
                continue

            mods = self._active_modifiers()
            self._send_via_backend("key", win, keysym, mods if mods else None)

    def _send_movement_key(self, action, key, enabled, modes):
        active_window = self._window_cache.get()

        for i, (is_enabled, mode) in enumerate(zip(enabled, modes)):
            if not is_enabled or i >= len(self.window_ids):
                continue
            if mode == "WASD" and key in ARROW_KEYS:
                continue
            if mode == "ARROWS" and key in WASD_KEYS:
                continue

            mapped = ARROW_TO_WASD.get(key, key) if mode == "ARROWS" else key
            keysym = self._resolve_keysym(mapped)
            if not keysym:
                continue

            win = self.window_ids[i]
            if self._xlib and win == active_window:
                continue  # real keyboard handles the focused window
            self._send_via_backend(action, win, keysym)

    def _release_movement_key(self, key, enabled, modes):
        self._send_movement_key("keyup", key, enabled, modes)

    def _send_backspace_to_background(self, enabled, modes):
        active_window = self._window_cache.get()
        for i, (is_enabled, mode) in enumerate(zip(enabled, modes)):
            if not is_enabled or i >= len(self.window_ids):
                continue
            win = self.window_ids[i]
            if win == active_window:
                continue
            self._send_via_backend("key", win, "BackSpace")

    def _resolve_keysym(self, key):
        if key in NAMED_KEYSYMS:
            return NAMED_KEYSYMS[key]
        lookup = key.lower() if len(key) == 1 and key.isalpha() else key
        if lookup in CHAR_TO_PHYSICAL_KEYSYM:
            return CHAR_TO_PHYSICAL_KEYSYM[lookup]
        return None

    def _send_via_backend(self, action: str, win_id: str, keysym: str, modifiers: list = None):
        """Route input through Xlib or xdotool depending on USE_XLIB_BACKEND."""
        if self._xlib:
            if action == "keydown":
                self._xlib.send_keydown(win_id, keysym)
            elif action == "keyup":
                self._xlib.send_keyup(win_id, keysym)
            elif action == "key":
                self._xlib.send_key(win_id, keysym, modifiers)
        else:
            if action == "keydown":
                self._safe_run(["xdotool", "keydown", "--window", win_id, keysym])
            elif action == "keyup":
                self._safe_run(["xdotool", "keyup", "--window", win_id, keysym])
            elif action == "key":
                if modifiers:
                    combo = '+'.join(modifiers + [keysym])
                    self._safe_run(["xdotool", "key", "--window", win_id, combo])
                else:
                    self._safe_run(["xdotool", "key", "--window", win_id, keysym])

    def _safe_run(self, cmd):
        try:
            subprocess.run(cmd, check=True, stderr=subprocess.DEVNULL)
            return True
        except subprocess.CalledProcessError:
            return False

    def release_all_keys(self):
        modes = self.get_movement_modes()
        enabled = self.get_enabled_toons()
        active_window = self._window_cache.get()
        for key in list(self.keys_held):
            for i, is_enabled in enumerate(enabled):
                if is_enabled and i < len(self.window_ids):
                    mapped = ARROW_TO_WASD.get(key, key) if modes[i] == "ARROWS" else key
                    keysym = self._resolve_keysym(mapped)
                    if keysym:
                        self._send_via_backend("keyup", self.window_ids[i], keysym)
        for key in list(self.modifiers_held):
            keysym = self._resolve_keysym(key)
            if keysym:
                for i, is_enabled in enumerate(enabled):
                    if is_enabled and i < len(self.window_ids):
                        if self.window_ids[i] != active_window:
                            self._send_via_backend("keyup", self.window_ids[i], keysym)
        self.keys_held.clear()
        self.modifiers_held.clear()
        self.bg_typing_held.clear()
        self.chat_active.clear()

    def send_keep_alive_key(self, key):
        keysym = self._resolve_keysym(key) or key
        for win_id in self.window_ids:
            self._send_via_backend("keydown", win_id, keysym)
            time.sleep(0.05)
            self._send_via_backend("keyup", win_id, keysym)