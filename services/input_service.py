import subprocess
import threading
import time
from collections import defaultdict
from PySide6.QtCore import QObject, Signal

ALPHA_NUM_KEYS = set("abcdefghijklmnopqrstuvwxyz1234567890`-=[]\\;',./")
SYMBOL_SHIFT_MAP = {
    "!": "1", "@": "2", "#": "3", "$": "4", "%": "5", "^": "6",
    "&": "7", "*": "8", "(": "9", ")": "0", "_": "-", "+": "=",
    "{": "[", "}": "]", "|": "\\", ":": ";", "\"": "'", "<": ",",
    ">": ".", "?": "/", "~": "`"
}
MODIFIER_KEYS = {"Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R"}
SPECIAL_KEYS = {"space", "Return", "BackSpace", "Tab", "Escape", "Delete", "Up", "Down", "Left", "Right"}

HOLDABLE_KEYS = ALPHA_NUM_KEYS | MODIFIER_KEYS | SPECIAL_KEYS
SYMBOL_KEYS = set(SYMBOL_SHIFT_MAP.keys()) | set(SYMBOL_SHIFT_MAP.values())
CHAT_KEYS = ALPHA_NUM_KEYS | SYMBOL_KEYS | {"space"}


class InputService(QObject):
    log_signal = Signal(str)
    window_ids_updated = Signal(list)

    def __init__(self, get_enabled_toons, get_movement_modes, get_pressed_keys_func, settings_manager=None):
        super().__init__()
        self.get_enabled_toons = get_enabled_toons
        self.get_movement_modes = get_movement_modes
        self.get_pressed_keys = get_pressed_keys_func
        self.settings_manager = settings_manager
        self.running = False
        self.thread = None
        self.window_ids = []
        self.keys_held = set()
        self.symbols_sent = set()
        self.last_sent = defaultdict(lambda: 0)

    def start(self):
        self.running = True
        self.assign_windows()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        self.release_all_keys()

    def assign_windows(self):
        try:
            raw_ids = subprocess.check_output(["xdotool", "search", "--class", "Toontown Rewritten"]).decode().strip().split("\n")
            visible_ids = []
            for wid in map(str.strip, raw_ids):
                try:
                    geo = subprocess.check_output(["xdotool", "getwindowgeometry", wid]).decode()
                    if "Position:" in geo and "Geometry:" in geo:
                        visible_ids.append(wid)
                except subprocess.CalledProcessError:
                    continue

            if self.settings_manager and self.settings_manager.get("left_to_right_assignment", False):
                def get_x(win_id):
                    try:
                        for line in subprocess.check_output(["xdotool", "getwindowgeometry", win_id]).decode().splitlines():
                            if "Position:" in line:
                                return int(line.split()[1].split(",")[0])
                    except:
                        return 99999
                visible_ids.sort(key=get_x)

            self.window_ids = list(dict.fromkeys(visible_ids))[:4]
        except subprocess.CalledProcessError:
            self.window_ids = []

        self.window_ids_updated.emit(self.window_ids)

    def run(self):
        while self.running:
            if not self.should_send_input():
                time.sleep(0.01)
                continue

            pressed = set(self.get_pressed_keys())
            enabled = self.get_enabled_toons()
            modes = self.get_movement_modes()

            if not self.window_ids:
                self.assign_windows()

            for key in pressed:
                if key in SYMBOL_KEYS and key not in self.symbols_sent:
                    self.send_to_enabled("symbol", key, enabled, modes)
                    self.symbols_sent.add(key)
                elif key not in self.keys_held:
                    self.keys_held.add(key)
                    self.send_to_enabled("keydown", key, enabled, modes)

            for key in (self.keys_held | self.symbols_sent) - pressed:
                if key in self.keys_held:
                    self.send_to_enabled("keyup", key, enabled, modes)
                    self.keys_held.remove(key)
                if key in self.symbols_sent:
                    self.symbols_sent.remove(key)

            time.sleep(0.01)

    def should_send_input(self):
        try:
            active = subprocess.check_output(["xdotool", "getactivewindow"]).decode().strip()
            if not active:
                return False
            if active in self.window_ids:
                return True
            if self.settings_manager and self.settings_manager.get("multitool_window_id"):
                return active == str(self.settings_manager.get("multitool_window_id"))
            return False
        except:
            return False

    def send_to_enabled(self, action, key, enabled, modes):
        for i, (is_enabled, mode) in enumerate(zip(enabled, modes)):
            if not is_enabled or i >= len(self.window_ids):
                continue
            if key == "Return" and mode == "ARROWS":
                continue
            if (mode == "WASD" and key in ["Up", "Down", "Left", "Right"]) or \
               (mode == "ARROWS" and key.lower() in ["w", "a", "s", "d"]):
                continue

            mapped = self.map_key(key, mode)
            if not mapped:
                continue
            win = self.window_ids[i]

            if action == "symbol":
                self.send_symbol_sequence(win, key, i)
                continue
            if mapped not in HOLDABLE_KEYS:
                continue

            debounce_key = f"{mapped}_{i}_{action}"
            if action == "keydown" and time.time() - self.last_sent[debounce_key] < 0.05:
                continue
            self.last_sent[debounce_key] = time.time()
            self.send_key(win, mapped, action)

    def send_key(self, win_id, key, action):
        self._safe_run(["xdotool", action, "--window", win_id, key],
                       f"[InputService] Error sending {action} '{key}' to {win_id}")

    def send_symbol_sequence(self, win_id, symbol, toon_index):
        debounce_id = f"type_{symbol}_{toon_index}"
        if time.time() - self.last_sent[debounce_id] > 0.05:
            if self._safe_run(["xdotool", "type", "--window", win_id, symbol]):
                time.sleep(0.01)
                self._safe_run(["xdotool", "keyup", "--window", win_id, "Shift_L"])
                self.last_sent[debounce_id] = time.time()

    def _safe_run(self, cmd, err_prefix=None):
        try:
            subprocess.run(cmd, check=True, stderr=subprocess.PIPE)
            return True
        except subprocess.CalledProcessError as e:
            if err_prefix:
                print(f"{err_prefix}:\n    {e.stderr.decode().strip()}")
            return False

    def release_all_keys(self):
        modes = self.get_movement_modes()
        for key in list(self.keys_held):
            for i, enabled in enumerate(self.get_enabled_toons()):
                if enabled and i < len(self.window_ids):
                    mapped = self.map_key(key, modes[i])
                    if mapped in HOLDABLE_KEYS:
                        self.send_key(self.window_ids[i], mapped, "keyup")
        self.keys_held.clear()
        self.symbols_sent.clear()

    def map_key(self, key, mode):
        return {"Up": "w", "Down": "s", "Left": "a", "Right": "d"}.get(key, key) if mode == "ARROWS" else key

    def send_keep_alive_key(self, key):
        for win_id in self.window_ids:
            if self._safe_run(["xdotool", "keydown", "--window", win_id, key]):
                time.sleep(0.05)
                self._safe_run(["xdotool", "keyup", "--window", win_id, key])
