import queue
import subprocess
import threading
import time
from functools import lru_cache
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

# Fix #8: Pre-built combined lookup dict for O(1) keysym resolution
_KEYSYM_LOOKUP = {}
_KEYSYM_LOOKUP.update(NAMED_KEYSYMS)
_KEYSYM_LOOKUP.update(CHAR_TO_PHYSICAL_KEYSYM)
# Add lowercase alpha mappings (handles the .lower() case)
for c in 'abcdefghijklmnopqrstuvwxyz':
    _KEYSYM_LOOKUP[c] = CHAR_TO_PHYSICAL_KEYSYM[c]





class InputService(QObject):
    log_signal = Signal(str)
    window_ids_updated = Signal(list)

    BACKSPACE_REPEAT_DELAY    = 0.4
    BACKSPACE_REPEAT_INTERVAL = 0.05

    def __init__(self, window_manager, get_enabled_toons, get_movement_modes, get_event_queue_func,
                 get_chat_enabled=None, settings_manager=None,
                 get_keymap_assignments=None, keymap_manager=None):
        super().__init__()
        self.window_manager = window_manager
        self.get_enabled_toons = get_enabled_toons
        self.get_movement_modes = get_movement_modes
        self.get_event_queue = get_event_queue_func
        self.get_chat_enabled = get_chat_enabled
        self.settings_manager = settings_manager
        self.get_keymap_assignments = get_keymap_assignments
        self.keymap_manager = keymap_manager
        self.running = False
        self.thread = None

        self.keys_held = set()
        self.bg_typing_held = set()
        self.modifiers_held = set()
        self.chat_active = set()

        self._xlib = None

    def start(self):
        self._apply_backend_setting()
        self.running = True
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
        self.release_all_keys()

    def shutdown(self):
        """Call once on app exit to clean up the Xlib connection."""
        self.stop()
        if self._xlib:
            self._xlib.disconnect()
            self._xlib = None



    # ── Keymap helpers ─────────────────────────────────────────────────────

    def _movement_keys(self) -> frozenset:
        """Return ALL movement keys across ALL sets so any set's keys enter the movement branch."""
        if self.keymap_manager:
            return self.keymap_manager.get_all_keys()
        return MOVEMENT_KEYS

    def _get_assignments(self, enabled) -> list:
        """Return per-toon set indices. Falls back to legacy WASD/ARROWS mapping."""
        if self.get_keymap_assignments:
            return self.get_keymap_assignments()
        # Legacy: ARROWS mode → index 1, WASD → index 0
        modes = self.get_movement_modes()
        return [1 if m == "ARROWS" else 0 for m in modes]

    # ── Keymap-aware send methods ──────────────────────────────────────────

    def _send_movement_key_km(self, action, key, enabled, assignments):
        """Send a movement key to background toons, translating through keymap.

        Each toon responds only to keys from its assigned set.
        Keys are translated TO Set 1 before sending, since all TTR clients
        use Set 1's movement config.
        """
        active_window = self.window_manager.get_active_window()

        for i, is_enabled in enumerate(enabled):
            if not is_enabled or i >= len(self.window_manager.ttr_window_ids):
                continue

            win = self.window_manager.ttr_window_ids[i]
            # Always skip focused window — real keyboard handles it
            if win == active_window:
                continue

            assignment = assignments[i] if i < len(assignments) else 0

            if self.keymap_manager:
                # Check if this key belongs to the toon's assigned set
                direction = self.keymap_manager.get_direction_in_set(assignment, key)
                if direction is None:
                    # Key doesn't belong to this toon's set — skip
                    continue

                # Translate to Set 1's key for this direction
                set1_key = self.keymap_manager.get_key_for_direction(0, direction)
                if set1_key is None:
                    continue

                keysym = self._resolve_keysym(set1_key)
                if keysym:
                    self._send_via_backend(action, win, keysym)
            else:
                # Legacy fallback (no keymap_manager)
                mode = self.get_movement_modes()[i] if i < len(self.get_movement_modes()) else "WASD"
                if mode == "WASD" and key in ARROW_KEYS:
                    continue
                if mode == "ARROWS" and key in WASD_KEYS:
                    continue
                mapped = ARROW_TO_WASD.get(key, key) if mode == "ARROWS" else key
                keysym = self._resolve_keysym(mapped)
                if keysym:
                    self._send_via_backend(action, win, keysym)

    def _send_modifier_to_bg(self, action, key, enabled, assignments):
        active_window = self.window_manager.get_active_window()
        keysym = self._resolve_keysym(key)
        if not keysym:
            return
        for i, is_enabled in enumerate(enabled):
            if not is_enabled or i >= len(self.window_manager.ttr_window_ids):
                continue
            win = self.window_manager.ttr_window_ids[i]
            if win != active_window:
                self._send_via_backend(action, win, keysym)

    def _send_typing_to_bg(self, key, enabled, assignments, movement_keys=None):
        active_window = self.window_manager.get_active_window()
        if movement_keys is None:
            movement_keys = self._movement_keys()

        for i, is_enabled in enumerate(enabled):
            if not is_enabled or i >= len(self.window_manager.ttr_window_ids):
                continue

            assignment = assignments[i] if i < len(assignments) else 0

            if self.keymap_manager:
                # Check if this key belongs to THIS toon's assigned set
                is_toon_movement_key = (
                    self.keymap_manager.get_direction_in_set(assignment, key) is not None
                )
                # Skip the toon's own movement keys (movement routing handles them)
                # unless chat is active for this toon
                if is_toon_movement_key and not self._is_chat_active(i):
                    continue
            else:
                # Legacy logic
                if assignment == 0 and key in movement_keys:
                    continue
                if assignment != 0 and key in movement_keys and not self._is_chat_active(i):
                    continue

            if key in ("Return", "Escape") and not self._is_chat_allowed(i):
                continue

            win = self.window_manager.ttr_window_ids[i]
            if win == active_window:
                continue

            keysym = self._resolve_keysym(key)
            if not keysym:
                continue

            mods = self._active_modifiers()
            self._send_via_backend("key", win, keysym, mods if mods else None)

    def _send_backspace_to_background(self, enabled, assignments):
        active_window = self.window_manager.get_active_window()
        for i, is_enabled in enumerate(enabled):
            if not is_enabled or i >= len(self.window_manager.ttr_window_ids):
                continue
            win = self.window_manager.ttr_window_ids[i]
            if win == active_window:
                continue
            self._send_via_backend("key", win, "BackSpace")

    # ── Legacy methods (kept for backward compat, unused with keymap) ──────

    def _send_movement_key(self, action, key, enabled, modes):
        active_window = self.window_manager.get_active_window()
        for i, (is_enabled, mode) in enumerate(zip(enabled, modes)):
            if not is_enabled or i >= len(self.window_manager.ttr_window_ids):
                continue
            if mode == "WASD" and key in ARROW_KEYS:
                continue
            if mode == "ARROWS" and key in WASD_KEYS:
                continue
            mapped = ARROW_TO_WASD.get(key, key) if mode == "ARROWS" else key
            keysym = self._resolve_keysym(mapped)
            if not keysym:
                continue
            win = self.window_manager.ttr_window_ids[i]
            if win == active_window:
                continue
            self._send_via_backend(action, win, keysym)

    def _release_movement_key(self, key, enabled, modes):
        self._send_movement_key("keyup", key, enabled, modes)

    # ── Run loop ───────────────────────────────────────────────────────────

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
                    enabled     = self.get_enabled_toons()
                    assignments = self._get_assignments(enabled)
                    for key in list(self.keys_held):
                        self._send_movement_key_km("keyup", key, enabled, assignments)
                    for key in list(self.modifiers_held):
                        self._send_modifier_to_bg("keyup", key, enabled, assignments)
                    self.keys_held.clear()
                    self.modifiers_held.clear()
                self.bg_typing_held.clear()
                bs_press_time  = None
                bs_last_repeat = 0.0
                time.sleep(0.01)
                continue

            now            = time.monotonic()
            enabled        = self.get_enabled_toons()
            assignments    = self._get_assignments(enabled)
            movement_keys  = self._movement_keys()

            if not self.window_manager.ttr_window_ids:
                self.assign_windows()

            while not event_queue.empty():
                try:
                    action, key = event_queue.get_nowait()
                except queue.Empty:
                    break

                if action == "keydown":

                    # When keymap is active, movement keys take priority over
                    # modifiers — e.g. Control_L as jump, Alt_L as book
                    is_movement = key in movement_keys
                    is_modifier = key in MODIFIER_KEYS and not is_movement

                    if is_modifier:
                        if key not in self.modifiers_held:
                            self.modifiers_held.add(key)
                            self._send_modifier_to_bg("keydown", key, enabled, assignments)

                    elif is_movement:
                        if key not in self.keys_held:
                            self.keys_held.add(key)
                            self._send_movement_key_km("keydown", key, enabled, assignments)
                            # Send movement keys as typing only for non-space keys
                            # (space is a jump key — sending it as typing causes double spaces)
                            if self.chat_active and key != "space":
                                self._send_typing_to_bg(key, enabled, assignments, movement_keys)

                    elif key == "BackSpace":
                        if key not in self.keys_held:
                            self.keys_held.add(key)
                            bs_press_time  = now
                            bs_last_repeat = 0.0
                            # BackSpace is a typing key, not a movement key —
                            # send directly to background toons, not via movement handler
                            self._send_backspace_to_background(enabled, assignments)

                    elif key == "Return":
                        if key not in self.bg_typing_held:
                            self.bg_typing_held.add(key)
                            for i in range(len(assignments)):
                                assignment = assignments[i] if i < len(assignments) else 0
                                if assignment != 0 and i < len(self.window_manager.ttr_window_ids) and enabled[i]:
                                    if not self._is_chat_allowed(i):
                                        pass
                                    elif i in self.chat_active:
                                        self.chat_active.discard(i)
                                    else:
                                        self.chat_active.add(i)
                            self._send_typing_to_bg(key, enabled, assignments, movement_keys)

                    elif key == "Escape":
                        if key not in self.bg_typing_held:
                            self.bg_typing_held.add(key)
                            for i in range(len(assignments)):
                                assignment = assignments[i] if i < len(assignments) else 0
                                if assignment != 0 and i < len(self.window_manager.ttr_window_ids) and enabled[i]:
                                    self.chat_active.discard(i)
                            self._send_typing_to_bg(key, enabled, assignments, movement_keys)

                    else:
                        if key not in self.bg_typing_held:
                            self.bg_typing_held.add(key)
                            self._send_typing_to_bg(key, enabled, assignments, movement_keys)

                elif action == "keyup":

                    is_modifier = key in MODIFIER_KEYS and key not in movement_keys

                    if is_modifier:
                        self.modifiers_held.discard(key)
                        self._send_modifier_to_bg("keyup", key, enabled, assignments)

                    elif key in self.keys_held:
                        self.keys_held.discard(key)
                        if key == "BackSpace":
                            bs_press_time  = None
                            bs_last_repeat = 0.0
                        self._send_movement_key_km("keyup", key, enabled, assignments)

                    else:
                        self.bg_typing_held.discard(key)

            if bs_press_time is not None and "BackSpace" in self.keys_held:
                held_for = now - bs_press_time
                if held_for >= self.BACKSPACE_REPEAT_DELAY:
                    if now - bs_last_repeat >= self.BACKSPACE_REPEAT_INTERVAL:
                        bs_last_repeat = now
                        self._send_backspace_to_background(enabled, assignments)

            time.sleep(0.005)

    def should_send_input(self):
        active = self.window_manager.get_active_window()
        if not active:
            return False
        if active in self.window_manager.ttr_window_ids:
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

    def _resolve_keysym(self, key):
        """Fix #8: O(1) lookup from pre-built dict instead of repeated branching."""
        result = _KEYSYM_LOOKUP.get(key)
        if result:
            return result
        if len(key) == 1 and key.isalpha():
            return _KEYSYM_LOOKUP.get(key.lower())
        return None

    def _send_via_backend(self, action: str, win_id: str, keysym: str, modifiers: list = None):
        """Route input through Xlib or xdotool depending on USE_XLIB_BACKEND."""
        success = True
        if self._xlib:
            if action == "keydown":
                success = self._xlib.send_keydown(win_id, keysym)
            elif action == "keyup":
                success = self._xlib.send_keyup(win_id, keysym)
            elif action == "key":
                success = self._xlib.send_key(win_id, keysym, modifiers)
        else:
            if action == "keydown":
                success = self._safe_run(["xdotool", "keydown", "--window", win_id, keysym])
            elif action == "keyup":
                success = self._safe_run(["xdotool", "keyup", "--window", win_id, keysym])
            elif action == "key":
                if modifiers:
                    combo = '+'.join(modifiers + [keysym])
                    success = self._safe_run(["xdotool", "key", "--window", win_id, combo])
                else:
                    success = self._safe_run(["xdotool", "key", "--window", win_id, keysym])
                    
        if not success:
            self.window_manager.assign_windows()

    def _safe_run(self, cmd):
        try:
            subprocess.run(cmd, check=True, stderr=subprocess.DEVNULL)
            return True
        except subprocess.CalledProcessError:
            return False

    def release_all_keys(self):
        assignments = self._get_assignments(self.get_enabled_toons())
        enabled = self.get_enabled_toons()
        active_window = self.window_manager.get_active_window()

        for key in list(self.keys_held):
            for i, is_enabled in enumerate(enabled):
                if is_enabled and i < len(self.window_manager.ttr_window_ids):
                    win = self.window_manager.ttr_window_ids[i]
                    if win == active_window:
                        continue
                    assignment = assignments[i] if i < len(assignments) else 0
                    if self.keymap_manager:
                        # Same logic as _send_movement_key_km: find direction
                        # in the toon's set, translate to Set 1
                        direction = self.keymap_manager.get_direction_in_set(assignment, key)
                        if direction is None:
                            continue
                        set1_key = self.keymap_manager.get_key_for_direction(0, direction)
                        keysym = self._resolve_keysym(set1_key) if set1_key else None
                    else:
                        modes = self.get_movement_modes()
                        mode = modes[i] if i < len(modes) else "WASD"
                        mapped = ARROW_TO_WASD.get(key, key) if mode == "ARROWS" else key
                        keysym = self._resolve_keysym(mapped)
                    if keysym:
                        self._send_via_backend("keyup", win, keysym)

        for key in list(self.modifiers_held):
            keysym = self._resolve_keysym(key)
            if keysym:
                for i, is_enabled in enumerate(enabled):
                    if is_enabled and i < len(self.window_manager.ttr_window_ids):
                        if self.window_manager.ttr_window_ids[i] != active_window:
                            self._send_via_backend("keyup", self.window_manager.ttr_window_ids[i], keysym)

        self.keys_held.clear()
        self.modifiers_held.clear()
        self.bg_typing_held.clear()
        self.chat_active.clear()

    def send_keep_alive_key(self, key):
        keysym = self._resolve_keysym(key) or key
        for win_id in self.window_manager.ttr_window_ids:
            self._send_via_backend("keydown", win_id, keysym)
            time.sleep(0.05)
            self._send_via_backend("keyup", win_id, keysym)

    def send_keep_alive_to_window(self, win_id, key):
        """Send a single keep-alive keypress to a specific window."""
        keysym = self._resolve_keysym(key) or key
        self._send_via_backend("keydown", win_id, keysym)
        time.sleep(0.05)
        self._send_via_backend("keyup", win_id, keysym)