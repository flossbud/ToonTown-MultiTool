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

    def __init__(self, get_enabled_toons, get_movement_modes, get_event_queue_func, settings_manager=None):
        super().__init__()
        self.get_enabled_toons = get_enabled_toons
        self.get_movement_modes = get_movement_modes
        self.get_event_queue = get_event_queue_func
        self.settings_manager = settings_manager
        self.running = False
        self.thread = None
        self.window_ids = []

        # Keys currently held for movement/backspace — need real hold semantics
        self.keys_held = set()

        # Typing keys currently held on background windows.
        # Used ONLY to suppress X11 auto-repeat (which fires keyup+keydown pairs).
        # The focused window is never sent xdotool typing events — real keyboard
        # handles it perfectly and needs no intervention from us.
        self.bg_typing_held = set()

        # Modifiers currently held: key -> True
        # Cleared on keyup. Used to build combos for background windows.
        self.modifiers_held = set()

        # Toon indices (ARROWS mode) that currently have chat box open
        self.chat_active = set()

        self._window_cache = ActiveWindowCache()

    def start(self):
        self.running = True
        self._window_cache.start()
        self.assign_windows()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        self._window_cache.stop()
        self.release_all_keys()

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

            if self.settings_manager and self.settings_manager.get("left_to_right_assignment", False):
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
                            # If this is a WASD key and any ARROWS toon has chat open,
                            # also send it as a typing tap to those toons so letters
                            # reach the chat box instead of being filtered as movement.
                            if key in WASD_KEYS and self.chat_active:
                                self._send_typing_to_bg(key, enabled, modes)

                    elif key == "BackSpace":
                        if key not in self.keys_held:
                            self.keys_held.add(key)
                            bs_press_time  = now
                            bs_last_repeat = 0.0
                            self._send_movement_key("keydown", key, enabled, modes)
                        # X11 auto-repeat keydowns swallowed — timer handles bg repeat

                    elif key == "Return":
                        # Toggle chat state for ARROWS toons.
                        # Only fire once per physical press (skip X11 auto-repeat).
                        if key not in self.bg_typing_held:
                            self.bg_typing_held.add(key)
                            for i, mode in enumerate(modes):
                                if mode == "ARROWS" and i < len(self.window_ids) and enabled[i]:
                                    if i in self.chat_active:
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
                        # Regular typing key.
                        # Focused window: do NOTHING — the real keyboard already
                        # delivers the keystroke perfectly with correct modifier state.
                        # Background windows: send one atomic tap, skip X11 repeats.
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
                        # Typing keyup: clear bg_typing_held so the next real
                        # press fires a new tap to background windows
                        self.bg_typing_held.discard(key)

            # Backspace repeat for background windows only
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

    def _is_chat_active(self, toon_index):
        return toon_index in self.chat_active

    def _send_modifier_to_bg(self, action, key, enabled, modes):
        """Send modifier keydown/keyup to background windows only."""
        active_window = self._window_cache.get()
        keysym = self._resolve_keysym(key)
        if not keysym:
            return
        for i, (is_enabled, mode) in enumerate(zip(enabled, modes)):
            if not is_enabled or i >= len(self.window_ids):
                continue
            win = self.window_ids[i]
            if win != active_window:
                self._safe_run(["xdotool", action, "--window", win, keysym])

    def _send_typing_to_bg(self, key, enabled, modes):
        """Send one atomic tap to background windows only.
        The focused window is deliberately skipped — the real keyboard already
        delivered the keystroke. We only need to mirror it to background windows."""
        active_window = self._window_cache.get()

        for i, (is_enabled, mode) in enumerate(zip(enabled, modes)):
            if not is_enabled or i >= len(self.window_ids):
                continue
            if mode == "ARROWS" and key in WASD_KEYS and not self._is_chat_active(i):
                continue
            if mode == "WASD" and key in ARROW_KEYS:
                continue

            win = self.window_ids[i]
            if win == active_window:
                continue  # real keyboard handles the focused window

            keysym = self._resolve_keysym(key)
            if not keysym:
                continue

            mods = self._active_modifiers()
            if mods:
                combo = '+'.join(mods + [keysym])
                self._safe_run(["xdotool", "key", "--window", win, combo])
            else:
                self._safe_run(["xdotool", "key", "--window", win, keysym])

    def _send_movement_key(self, action, key, enabled, modes):
        """Send movement key keydown to all enabled windows."""
        active_window = self._window_cache.get()

        for i, (is_enabled, mode) in enumerate(zip(enabled, modes)):
            if not is_enabled or i >= len(self.window_ids):
                continue
            if mode == "WASD" and key in ARROW_KEYS:
                continue
            # Skip WASD keys on ARROWS toons — but also skip if chat is open
            # (those toons receive WASD as typing letters via _send_typing_to_bg)
            if mode == "ARROWS" and key in WASD_KEYS:
                continue

            mapped = ARROW_TO_WASD.get(key, key) if mode == "ARROWS" else key
            keysym = self._resolve_keysym(mapped)
            if not keysym:
                continue

            win = self.window_ids[i]
            self._safe_run(["xdotool", action, "--window", win, keysym])

    def _release_movement_key(self, key, enabled, modes):
        """Send keyup for a movement key to all enabled windows."""
        self._send_movement_key("keyup", key, enabled, modes)

    def _send_backspace_to_background(self, enabled, modes):
        """Controlled backspace repeat tap to background windows."""
        active_window = self._window_cache.get()
        for i, (is_enabled, mode) in enumerate(zip(enabled, modes)):
            if not is_enabled or i >= len(self.window_ids):
                continue
            win = self.window_ids[i]
            if win == active_window:
                continue
            self._safe_run(["xdotool", "key", "--window", win, "BackSpace"])

    def _resolve_keysym(self, key):
        if key in NAMED_KEYSYMS:
            return NAMED_KEYSYMS[key]
        lookup = key.lower() if len(key) == 1 and key.isalpha() else key
        if lookup in CHAR_TO_PHYSICAL_KEYSYM:
            return CHAR_TO_PHYSICAL_KEYSYM[lookup]
        return None

    def _safe_run(self, cmd):
        try:
            subprocess.run(cmd, check=True, stderr=subprocess.DEVNULL)
            return True
        except subprocess.CalledProcessError:
            return False

    def release_all_keys(self):
        """Send keyup for every tracked key to all enabled background windows."""
        modes = self.get_movement_modes()
        enabled = self.get_enabled_toons()
        active_window = self._window_cache.get()
        for key in list(self.keys_held):
            for i, is_enabled in enumerate(enabled):
                if is_enabled and i < len(self.window_ids):
                    mapped = ARROW_TO_WASD.get(key, key) if modes[i] == "ARROWS" else key
                    keysym = self._resolve_keysym(mapped)
                    if keysym:
                        self._safe_run(["xdotool", "keyup", "--window",
                                        self.window_ids[i], keysym])
        for key in list(self.modifiers_held):
            keysym = self._resolve_keysym(key)
            if keysym:
                for i, is_enabled in enumerate(enabled):
                    if is_enabled and i < len(self.window_ids):
                        if self.window_ids[i] != active_window:
                            self._safe_run(["xdotool", "keyup", "--window",
                                            self.window_ids[i], keysym])
        self.keys_held.clear()
        self.modifiers_held.clear()
        self.bg_typing_held.clear()
        self.chat_active.clear()

    def send_keep_alive_key(self, key):
        keysym = self._resolve_keysym(key) or key
        for win_id in self.window_ids:
            if self._safe_run(["xdotool", "keydown", "--window", win_id, keysym]):
                time.sleep(0.05)
                self._safe_run(["xdotool", "keyup", "--window", win_id, keysym])