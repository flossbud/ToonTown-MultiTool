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
    # Numpad keys
    'KP_0': 'KP_0', 'KP_1': 'KP_1', 'KP_2': 'KP_2', 'KP_3': 'KP_3',
    'KP_4': 'KP_4', 'KP_5': 'KP_5', 'KP_6': 'KP_6', 'KP_7': 'KP_7',
    'KP_8': 'KP_8', 'KP_9': 'KP_9',
    'KP_Decimal':  'KP_Decimal',
    'KP_Enter':    'KP_Enter',
    'KP_Add':      'KP_Add',
    'KP_Subtract': 'KP_Subtract',
    'KP_Multiply': 'KP_Multiply',
    'KP_Divide':   'KP_Divide',
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
    input_log = Signal(str)
    window_ids_updated = Signal(list)
    chat_state_changed = Signal(bool)  # True = chat active, False = chat inactive

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
        self._stop_event = threading.Event()
        self.logging_enabled = False

        self.keys_held = set()
        self.bg_typing_held = set()
        self.modifiers_held = set()
        self.chat_active = set()
        self.global_chat_active = False

        # Phantom chat detection — catches whisper replies opened via mouse click
        self._phantom_char_count = 0
        self._phantom_active = False
        self._chat_last_activity = 0.0
        self.CHAT_IDLE_TIMEOUT = 15.0

        self._xlib = None

    def start(self):
        if self.running and self.thread is not None and self.thread.is_alive():
            return
        self._apply_backend_setting()
        self._stop_event.clear()
        self.running = True
        self.thread = threading.Thread(target=self.run, daemon=False)
        self.thread.start()

    def _apply_backend_setting(self):
        """Connect or disconnect backend based on platform and current settings."""
        import sys
        if sys.platform == "win32":
            if self._xlib is None:
                try:
                    from utils.win32_backend import Win32Backend
                    self._xlib = Win32Backend()
                    self._xlib.connect()
                except Exception as e:
                    print(f"[InputService] Win32 backend unavailable: {e}")
                    self._xlib = None
            return

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
        self._stop_event.set()
        self.release_all_keys()
        if self.thread is not None and self.thread.is_alive():
            self.thread.join(timeout=2.0)

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
        if self.global_chat_active:
            return

        active_window = self.window_manager.get_active_window()
        window_ids = self.window_manager.get_window_ids()

        for i, is_enabled in enumerate(enabled):
            if not is_enabled or i >= len(window_ids):
                continue

            win = window_ids[i]
            # Always skip focused window — real keyboard handles it
            if win == active_window:
                continue

            assignment = assignments[i] if i < len(assignments) else 0

            if self.keymap_manager:
                # Find the direction for the physical key pressed by seeing if it exists in the toon's assigned set
                direction = self.keymap_manager.get_direction_in_set(assignment, key)
                if direction is None:
                    continue

                # Translate to Set 1's key for this direction (because all TTR instances share bindings)
                set1_key = self.keymap_manager.get_key_for_direction(0, direction)
                if set1_key is None:
                    continue

                keysym = self._resolve_keysym(set1_key)
                if keysym:
                    self._send_via_backend(action, win, keysym)
                    if self.logging_enabled and action == "keydown" and key != set1_key:
                        self.input_log.emit(
                            f"[Input] Key '{key}' → '{set1_key}' "
                            f"(direction: {direction}, set {assignment + 1} → set 1)"
                        )
            else:
                # Legacy fallback (no keymap_manager)
                modes = self.get_movement_modes()
                mode = modes[i] if i < len(modes) else "WASD"
                if mode == "WASD" and key in ARROW_KEYS:
                    continue
                if mode == "ARROWS" and key in WASD_KEYS:
                    continue
                mapped = ARROW_TO_WASD.get(key, key) if mode == "ARROWS" else key
                keysym = self._resolve_keysym(mapped)
                if keysym:
                    self._send_via_backend(action, win, keysym)
                    if self.logging_enabled and action == "keydown" and key != mapped:
                        self.input_log.emit(
                            f"[Input] Key '{key}' → '{mapped}' (legacy {mode} conversion)"
                        )

    def _send_modifier_to_bg(self, action, key, enabled, assignments):
        active_window = self.window_manager.get_active_window()
        keysym = self._resolve_keysym(key)
        if not keysym:
            return
        window_ids = self.window_manager.get_window_ids()
        for i, is_enabled in enumerate(enabled):
            if not is_enabled or i >= len(window_ids):
                continue
            win = window_ids[i]
            if win != active_window:
                self._send_via_backend(action, win, keysym)

    def _send_typing_to_bg(self, key, enabled, assignments, movement_keys=None):
        active_window = self.window_manager.get_active_window()
        if movement_keys is None:
            movement_keys = self._movement_keys()
        window_ids = self.window_manager.get_window_ids()

        for i, is_enabled in enumerate(enabled):
            if not is_enabled or i >= len(window_ids):
                continue

            assignment = assignments[i] if i < len(assignments) else 0

            if self.keymap_manager:
                # Check if this key belongs to THIS toon's assigned set
                is_toon_movement_key = (
                    self.keymap_manager.get_direction_in_set(assignment, key) is not None
                )
                # Skip the toon's own movement keys because _send_movement_key_km
                # already sends the native Set 1 translation as a keydown event,
                # which naturally types the character into the chatbox in Panda3D.
                if is_toon_movement_key and not self.global_chat_active:
                    continue
            else:
                # Legacy logic
                if assignment == 0 and key in movement_keys:
                    continue
                if assignment != 0 and key in movement_keys and not self._is_chat_active(i):
                    continue

            if self.global_chat_active and not self._is_chat_allowed(i):
                # If the active window is chatting, only pass keys to background windows that are ALSO chatting.
                continue

            if key in ("Return", "Escape") and not self._is_chat_allowed(i):
                continue

            win = window_ids[i]
            if win == active_window:
                continue

            keysym = self._resolve_keysym(key)
            if not keysym:
                continue

            mods = self._active_modifiers()
            self._send_via_backend("key", win, keysym, mods if mods else None)

    def _send_backspace_to_background(self, enabled, assignments):
        active_window = self.window_manager.get_active_window()
        window_ids = self.window_manager.get_window_ids()
        for i, is_enabled in enumerate(enabled):
            if not is_enabled or i >= len(window_ids):
                continue
            win = window_ids[i]
            if win == active_window:
                continue
            self._send_via_backend("key", win, "BackSpace")

    # ── Legacy methods (kept for backward compat, unused with keymap) ──────

    def _send_movement_key(self, action, key, enabled, modes):
        active_window = self.window_manager.get_active_window()
        window_ids = self.window_manager.get_window_ids()
        for i, (is_enabled, mode) in enumerate(zip(enabled, modes)):
            if not is_enabled or i >= len(window_ids):
                continue
            if mode == "WASD" and key in ARROW_KEYS:
                continue
            if mode == "ARROWS" and key in WASD_KEYS:
                continue
            mapped = ARROW_TO_WASD.get(key, key) if mode == "ARROWS" else key
            keysym = self._resolve_keysym(mapped)
            if not keysym:
                continue
            win = window_ids[i]
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
                self._phantom_reset()
                if self.global_chat_active:
                    self._set_chat_active(False)
                    self.chat_active.clear()
                bs_press_time  = None
                bs_last_repeat = 0.0
                self._stop_event.wait(0.01)
                continue

            now            = time.monotonic()
            enabled        = self.get_enabled_toons()
            assignments    = self._get_assignments(enabled)
            movement_keys  = self._movement_keys()

            # Idle timeout — reset chat state if no typing for 15s
            if (self.global_chat_active or self._phantom_active) and self._chat_last_activity > 0:
                if now - self._chat_last_activity > self.CHAT_IDLE_TIMEOUT:
                    self._timeout_reset_chat(enabled, assignments)

            window_ids = self.window_manager.get_window_ids()
            if not window_ids:
                self.window_manager.assign_windows()
                window_ids = self.window_manager.get_window_ids()

            while not event_queue.empty():
                try:
                    action, key = event_queue.get_nowait()
                except queue.Empty:
                    break

                if action == "keydown":

                    # When keymap is active, movement keys take priority over
                    # modifiers — e.g. Control_L as jump, Alt_L as book.
                    # BUT when chat is active, modifier keys (e.g. Shift_L mapped
                    # to "map") must act as modifiers so shifted typing works.
                    is_movement = key in movement_keys
                    is_modifier = key in MODIFIER_KEYS and (
                        not is_movement or self.global_chat_active or self._phantom_active
                    )
                    if is_modifier:
                        is_movement = False

                    if is_modifier:
                        if key not in self.modifiers_held:
                            self.modifiers_held.add(key)
                            self._send_modifier_to_bg("keydown", key, enabled, assignments)

                    elif is_movement:
                        if key not in self.keys_held:
                            self.keys_held.add(key)
                            if self.logging_enabled:
                                direction = None
                                if self.keymap_manager:
                                    for a in set(assignments):
                                        direction = self.keymap_manager.get_direction_in_set(a, key)
                                        if direction:
                                            break
                                extra = f" (direction: {direction})" if direction else ""
                                self._log_key(key, "pressed", extra)
                            if self._phantom_active:
                                # Stealth chat — suppress movement to bg toons
                                self._chat_last_activity = now
                            else:
                                self._send_movement_key_km("keydown", key, enabled, assignments)
                                # When global chat is active, movement keys (including space)
                                # are suppressed natively, so we must broadcast them via typing.
                                if self.global_chat_active:
                                    self._chat_last_activity = now
                                    self._send_typing_to_bg(key, enabled, assignments, movement_keys)

                    elif key == "BackSpace":
                        if key not in self.keys_held:
                            self.keys_held.add(key)
                            self._log_key(key, "pressed")
                            bs_press_time  = now
                            bs_last_repeat = 0.0
                            if self._phantom_active:
                                self._chat_last_activity = now
                            else:
                                self._send_backspace_to_background(enabled, assignments)

                    elif key == "Return":
                        if key not in self.bg_typing_held:
                            self.bg_typing_held.add(key)
                            self._log_key(key, "pressed")
                            if self._phantom_active:
                                # Whisper send detected — don't toggle chat on bg toons
                                self._phantom_reset()
                            else:
                                self._set_chat_active(not self.global_chat_active)
                                self._chat_last_activity = now if self.global_chat_active else 0.0
                                for i in range(min(len(assignments), len(enabled))):
                                    if i < len(window_ids) and enabled[i]:
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
                            self._log_key(key, "pressed")
                            was_chatting = self.global_chat_active
                            self._set_chat_active(False)
                            self.chat_active.clear()
                            self._phantom_reset()
                            if was_chatting:
                                self._send_typing_to_bg(key, enabled, assignments, movement_keys)

                    else:
                        if key not in self.bg_typing_held:
                            self.bg_typing_held.add(key)
                            if self._phantom_active:
                                # Stealth chat mode — suppress all forwarding
                                self._chat_last_activity = now
                            elif not self.global_chat_active and len(key) == 1 and key.isprintable():
                                # Typing without chat open — possible whisper reply
                                self._phantom_char_count += 1
                                if self._phantom_char_count >= 3:
                                    self._phantom_active = True
                                    self._chat_last_activity = now
                                    if self.logging_enabled:
                                        self.input_log.emit("[Input] Whisper reply detected — input suppressed")
                                else:
                                    self._send_typing_to_bg(key, enabled, assignments, movement_keys)
                            else:
                                if self.global_chat_active:
                                    self._chat_last_activity = now
                                self._send_typing_to_bg(key, enabled, assignments, movement_keys)

                elif action == "keyup":

                    # Check actual membership rather than re-classifying, since
                    # chat state may have changed between keydown and keyup.
                    if key in self.modifiers_held:
                        self.modifiers_held.discard(key)
                        self._send_modifier_to_bg("keyup", key, enabled, assignments)

                    elif key in self.keys_held:
                        self.keys_held.discard(key)
                        self._log_key(key, "released")
                        if key == "BackSpace":
                            bs_press_time  = None
                            bs_last_repeat = 0.0
                        self._send_movement_key_km("keyup", key, enabled, assignments)

                    else:
                        self.bg_typing_held.discard(key)

            if bs_press_time is not None and "BackSpace" in self.keys_held and not self._phantom_active:
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
        if active in self.window_manager.get_window_ids():
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

    def _focused_toon_tag(self):
        active_wid = self.window_manager.get_active_window()
        for i, wid in enumerate(self.window_manager.get_window_ids()):
            if wid == active_wid:
                return f" [Toon {i + 1}]"
        return ""

    def _log_key(self, key, state, extra=""):
        if not self.logging_enabled:
            return
        tag = self._focused_toon_tag()
        self.input_log.emit(f"[Input]{tag} '{key}' {state}{extra}")

    def _set_chat_active(self, active: bool):
        """Set global_chat_active and emit signal on change."""
        if self.global_chat_active != active:
            self.global_chat_active = active
            self.chat_state_changed.emit(active)
            if self.logging_enabled:
                self.input_log.emit(f"[Input] Chat broadcast {'activated' if active else 'deactivated'}")

    def _phantom_reset(self):
        """Reset phantom (stealth whisper) detection state."""
        self._phantom_char_count = 0
        self._phantom_active = False
        self._chat_last_activity = 0.0

    def _timeout_reset_chat(self, enabled, assignments):
        """Idle timeout fired — send Escape to bg toons to close any open chat, then reset."""
        if self.logging_enabled:
            self.input_log.emit("[Input] Chat idle timeout — resetting chat state")
        if self.global_chat_active:
            active_window = self.window_manager.get_active_window()
            window_ids = self.window_manager.get_window_ids()
            for i, is_enabled in enumerate(enabled):
                if not is_enabled or i >= len(window_ids):
                    continue
                win = window_ids[i]
                if win != active_window:
                    self._send_via_backend("key", win, "Escape")
        self._set_chat_active(False)
        self.chat_active.clear()
        self._phantom_reset()

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
        window_ids = self.window_manager.get_window_ids()

        for key in list(self.keys_held):
            for i, is_enabled in enumerate(enabled):
                if is_enabled and i < len(window_ids):
                    win = window_ids[i]
                    if win == active_window:
                        continue
                    assignment = assignments[i] if i < len(assignments) else 0
                    if self.keymap_manager:
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
                    if is_enabled and i < len(window_ids):
                        if window_ids[i] != active_window:
                            self._send_via_backend("keyup", window_ids[i], keysym)

        self.keys_held.clear()
        self.modifiers_held.clear()
        self.bg_typing_held.clear()
        self.chat_active.clear()
        self._set_chat_active(False)
        self._phantom_reset()

    def send_keep_alive_key(self, key):
        keysym = self._resolve_keysym(key) or key
        for win_id in self.window_manager.get_window_ids():
            self._send_via_backend("keydown", win_id, keysym)
            time.sleep(0.05)
            self._send_via_backend("keyup", win_id, keysym)

    def send_keep_alive_to_window(self, win_id, key, modifiers=None):
        """Send a single keep-alive keypress to a specific window."""
        keysym = self._resolve_keysym(key) or key
        if modifiers:
            self._send_via_backend("key", win_id, keysym, modifiers)
        else:
            self._send_via_backend("keydown", win_id, keysym)
            time.sleep(0.05)
            self._send_via_backend("keyup", win_id, keysym)
