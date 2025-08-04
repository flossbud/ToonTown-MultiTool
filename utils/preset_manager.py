import os
import json


class PresetManager:
    def __init__(self):
        config_dir = os.path.expanduser("~/.config/toontown_multitool")
        os.makedirs(config_dir, exist_ok=True)
        self.preset_path = os.path.join(config_dir, "presets.json")
        self._load_all_presets()

    def _load_all_presets(self):
        if not os.path.exists(self.preset_path):
            self.presets = {}
            return
        try:
            with open(self.preset_path, "r") as f:
                self.presets = json.load(f)
        except Exception as e:
            print(f"[PresetManager] Failed to load presets: {e}")
            self.presets = {}

    def _save_all_presets(self):
        try:
            with open(self.preset_path, "w") as f:
                json.dump(self.presets, f, indent=2)
                f.flush()  # ✅ ensure it writes immediately
        except Exception as e:
            print(f"[PresetManager] Failed to save presets: {e}")

    def save_preset(self, index, data):
        print(f"[PresetManager] Writing preset {index}: {data}")  # ✅ debug
        self.presets[str(index)] = data
        self._save_all_presets()
        print(f"[PresetManager] Preset {index} saved.")

    def load_preset(self, index):
        preset = self.presets.get(str(index), None)
        print(f"[PresetManager] Loaded preset {index}: {preset}")  # ✅ debug
        return preset
