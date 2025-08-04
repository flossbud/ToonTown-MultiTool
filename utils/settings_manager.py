import os
import json


class SettingsManager:
    def __init__(self):
        config_dir = os.path.expanduser("~/.config/toontown_multitool")
        os.makedirs(config_dir, exist_ok=True)
        self.settings_path = os.path.join(config_dir, "settings.json")
        self.settings = {
            "left_to_right_assignment": False,
            "show_debug_tab": False,
            "show_extras_tab": False,  # ✅ New extras tab toggle
            "keep_alive_key": "",
            "keep_alive_delay": "30 sec",
            "theme": "system"
        }
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


# Safe wrapper for use in theme_manager.py or elsewhere
def safe_get_theme(settings_manager):
    if settings_manager is None:
        return "dark"
    return settings_manager.get("theme", "system")
