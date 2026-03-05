import os
import json

from utils.models import ToonProfile

NUM_PROFILES = 5
DEFAULT_NAMES = [f"Profile {i+1}" for i in range(NUM_PROFILES)]


class ProfileManager:
    """
    Manages 5 named profiles. Each profile stores:
      - name (str)
      - enabled_toons (list of bool, length 4)
      - movement_modes (list of str, length 4)

    Profiles are always persisted immediately on any change.
    """

    def __init__(self):
        config_dir = os.path.expanduser("~/.config/toontown_multitool")
        os.makedirs(config_dir, exist_ok=True)
        self._path = os.path.join(config_dir, "profiles.json")
        self._profiles = []
        self._load()

    # ── Persistence ────────────────────────────────────────────────────────

    def _default_profile(self, index: int) -> dict:
        return {
            "name": DEFAULT_NAMES[index],
            "enabled_toons": [False, False, False, False],
            "movement_modes": ["Default", "Default", "Default", "Default"],
        }

    def _load(self):
        if os.path.exists(self._path):
            try:
                with open(self._path, "r") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    self._profiles = data
            except Exception as e:
                print(f"[ProfileManager] Failed to load: {e}")

        # Ensure exactly NUM_PROFILES entries
        while len(self._profiles) < NUM_PROFILES:
            self._profiles.append(self._default_profile(len(self._profiles)))
        self._profiles = self._profiles[:NUM_PROFILES]

        # Back-fill any missing keys
        for i, p in enumerate(self._profiles):
            if "name" not in p:
                p["name"] = DEFAULT_NAMES[i]
            if "enabled_toons" not in p:
                p["enabled_toons"] = [False, False, False, False]
            if "movement_modes" not in p:
                p["movement_modes"] = ["Default", "Default", "Default", "Default"]

    def _save(self):
        try:
            with open(self._path, "w") as f:
                json.dump(self._profiles, f, indent=2)
                f.flush()
        except Exception as e:
            print(f"[ProfileManager] Failed to save: {e}")

    # ── Read API ───────────────────────────────────────────────────────────

    def get_profile(self, index: int) -> ToonProfile:
        """Return a copy of the profile at index (0-based) as ToonProfile."""
        if 0 <= index < NUM_PROFILES:
            return ToonProfile.from_dict(self._profiles[index])
        return ToonProfile.from_dict(self._default_profile(index))

    def get_name(self, index: int) -> str:
        return self._profiles[index].get("name", DEFAULT_NAMES[index])

    def get_all_names(self) -> list:
        return [p.get("name", DEFAULT_NAMES[i]) for i, p in enumerate(self._profiles)]

    # ── Write API ──────────────────────────────────────────────────────────

    def save_profile(self, index: int, enabled_toons: list, movement_modes: list):
        """Overwrite the data portion of a profile. Preserves its name."""
        if 0 <= index < NUM_PROFILES:
            self._profiles[index]["enabled_toons"] = list(enabled_toons)
            self._profiles[index]["movement_modes"] = list(movement_modes)
            self._save()

    def rename_profile(self, index: int, name: str):
        if 0 <= index < NUM_PROFILES:
            name = name.strip() or DEFAULT_NAMES[index]
            self._profiles[index]["name"] = name
            self._save()

    def move_up(self, index: int):
        """Swap profile at index with the one above it."""
        if 1 <= index < NUM_PROFILES:
            self._profiles[index - 1], self._profiles[index] = (
                self._profiles[index], self._profiles[index - 1]
            )
            self._save()

    def move_down(self, index: int):
        """Swap profile at index with the one below it."""
        if 0 <= index < NUM_PROFILES - 1:
            self._profiles[index], self._profiles[index + 1] = (
                self._profiles[index + 1], self._profiles[index]
            )
            self._save()