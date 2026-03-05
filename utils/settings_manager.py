import os
import json


class SettingsManager:
    def __init__(self):
        config_dir = os.path.expanduser("~/.config/toontown_multitool")
        os.makedirs(config_dir, exist_ok=True)
        self.settings_path = os.path.join(config_dir, "settings.json")
        self.settings = {
            "show_debug_tab":        False,
            "show_diagnostics_tab":  False,
            "keep_alive_action":     "jump",
            "keep_alive_delay":      "30 sec",
            "theme":                 "system",
            "enable_companion_app":  True,
            "input_backend":         "xlib",
            "active_profile":        -1,
        }
        self._callbacks = []
        self._load()

    def _load(self):
        if os.path.exists(self.settings_path):
            try:
                with open(self.settings_path, "r") as f:
                    data = json.load(f)
                    self.settings.update(data)
            except Exception as e:
                print(f"[SettingsManager] Failed to load settings: {e}")

    def save(self):
        try:
            with open(self.settings_path, "w") as f:
                json.dump(self.settings, f, indent=2)
        except Exception as e:
            print(f"[SettingsManager] Failed to save settings: {e}")

    def get(self, key, default=None):
        return self.settings.get(key, default)

    def set(self, key, value):
        self.settings[key] = value
        self.save()
        for cb in self._callbacks:
            try:
                cb(key, value)
            except Exception:
                pass

    def on_change(self, callback):
        """Register callback(key, value) to be called when any setting changes."""
        self._callbacks.append(callback)


def safe_get_theme(settings_manager):
    if settings_manager is None:
        return "dark"
    return settings_manager.get("theme", "system")