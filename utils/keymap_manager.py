"""
Keymap Manager — stores and translates movement sets.

Movement sets are persisted as JSON at ~/.config/toontown_multitool/keymaps.json.
Each set has 5 slots: up, left, down, right, jump.

Set 1 is always the TTR default (what the user physically presses).
Additional sets define what keys a background toon's TTR client expects.
The input service translates: "user pressed W → Set-1 up direction →
toon on Set-2 receives Up Arrow."
"""

import os
import json
import threading

DIRECTIONS = ("up", "left", "down", "right", "jump", "book")

DEFAULT_SETS = [
    {
        "name": "Default",
        "up": "w",
        "left": "a",
        "down": "s",
        "right": "d",
        "jump": "space",
        "book": "Alt_L",
    },
    {
        "name": "Arrows",
        "up": "Up",
        "left": "Left",
        "down": "Down",
        "right": "Right",
        "jump": "Control_L",
        "book": "Alt_R",
    },
]


class KeymapManager:
    def __init__(self):
        config_dir = os.path.expanduser("~/.config/toontown_multitool")
        os.makedirs(config_dir, exist_ok=True)
        self._path = os.path.join(config_dir, "keymaps.json")
        self._lock = threading.Lock()
        self._listeners = []
        self._sets = []
        self._load()

    # ── Persistence ────────────────────────────────────────────────────────

    def _load(self):
        if os.path.exists(self._path):
            try:
                with open(self._path, "r") as f:
                    data = json.load(f)
                if isinstance(data, list) and len(data) >= 1:
                    self._sets = data
                    return
            except Exception as e:
                print(f"[KeymapManager] Failed to load keymaps: {e}")
        # Fallback: use defaults
        self._sets = [dict(s) for s in DEFAULT_SETS]
        self._save()

    def _save(self):
        try:
            with open(self._path, "w") as f:
                json.dump(self._sets, f, indent=2)
                f.flush()
        except Exception as e:
            print(f"[KeymapManager] Failed to save keymaps: {e}")

    # ── Change notification ────────────────────────────────────────────────

    def on_change(self, callback):
        """Register a callback to be called when sets are added/deleted/modified."""
        self._listeners.append(callback)

    def _notify(self):
        for cb in self._listeners:
            try:
                cb()
            except Exception as e:
                print(f"[KeymapManager] Listener error: {e}")

    # ── Read API ───────────────────────────────────────────────────────────

    def get_sets(self) -> list:
        """Return a copy of all movement sets."""
        with self._lock:
            return [dict(s) for s in self._sets]

    def get_set(self, index: int) -> dict | None:
        with self._lock:
            if 0 <= index < len(self._sets):
                return dict(self._sets[index])
            return None

    def get_set_names(self) -> list:
        """Return list of set names, e.g. ['TTR Default', 'Arrows', ...]."""
        with self._lock:
            return [s.get("name", f"Set {i+1}") for i, s in enumerate(self._sets)]

    def num_sets(self) -> int:
        with self._lock:
            return len(self._sets)

    def get_set1_keys(self) -> frozenset:
        """Return the frozenset of physical keys the user presses (Set 1)."""
        with self._lock:
            s = self._sets[0]
            return frozenset(s[d] for d in DIRECTIONS)

    def get_all_keys(self) -> frozenset:
        """Return frozenset of ALL keys across ALL movement sets."""
        with self._lock:
            keys = set()
            for s in self._sets:
                for d in DIRECTIONS:
                    k = s.get(d)
                    if k:
                        keys.add(k)
            return frozenset(keys)

    def get_direction(self, key: str) -> str | None:
        """Given a Set-1 physical key, return which direction it maps to."""
        with self._lock:
            s = self._sets[0]
            for d in DIRECTIONS:
                if s[d] == key:
                    return d
            return None

    def get_direction_in_set(self, set_index: int, key: str) -> str | None:
        """Given a key and set index, return which direction it maps to in that set."""
        with self._lock:
            if 0 <= set_index < len(self._sets):
                s = self._sets[set_index]
                for d in DIRECTIONS:
                    if s[d] == key:
                        return d
            return None

    def get_key_for_direction(self, set_index: int, direction: str) -> str | None:
        """Return the key that a given set uses for a direction."""
        with self._lock:
            if 0 <= set_index < len(self._sets):
                return self._sets[set_index].get(direction)
            return None

    def translate(self, pressed_key: str, target_set_index: int) -> str | None:
        """Convenience: translate a Set-1 physical key to the target set's key."""
        direction = self.get_direction(pressed_key)
        if direction is None:
            return None
        return self.get_key_for_direction(target_set_index, direction)

    # ── Write API ──────────────────────────────────────────────────────────

    MAX_SETS = 8

    def next_default_name(self, exclude_index: int = -1):
        """Return the next available default name: 'New Set', 'New Set 1', 'New Set 2', etc.
        exclude_index: skip this set when checking (for renaming the set itself)."""
        with self._lock:
            existing = set()
            for i, s in enumerate(self._sets):
                if i == exclude_index:
                    continue
                n = s.get("name", "")
                if n == "New Set" or (n.startswith("New Set ") and n[8:].isdigit()):
                    existing.add(n)
        if "New Set" not in existing:
            return "New Set"
        i = 1
        while f"New Set {i}" in existing:
            i += 1
        return f"New Set {i}"

    def add_set(self, name: str = None, keys: dict = None):
        """Add a new movement set. keys is optional {direction: key_str}. Max 8 sets."""
        if name is None:
            name = self.next_default_name()
        new_set = {"name": name}
        if keys:
            for d in DIRECTIONS:
                new_set[d] = keys.get(d, "")
        else:
            # Default to arrow keys + ctrl + alt
            new_set.update({
                "up": "Up", "left": "Left", "down": "Down",
                "right": "Right", "jump": "Control_L", "book": "Alt_R",
            })
        with self._lock:
            if len(self._sets) >= self.MAX_SETS:
                return
            self._sets.append(new_set)
            self._save()
        self._notify()

    def delete_set(self, index: int):
        """Delete a set. Set 1 (index 0) cannot be deleted."""
        if index <= 0:
            return
        with self._lock:
            if index < len(self._sets):
                self._sets.pop(index)
                self._save()
        self._notify()

    def update_set_name(self, index: int, name: str):
        """Rename a movement set."""
        with self._lock:
            if 0 <= index < len(self._sets):
                self._sets[index]["name"] = name
                self._save()
        self._notify()

    def update_set_key(self, set_index: int, direction: str, key: str):
        """Update a single key binding in a movement set."""
        if direction not in DIRECTIONS:
            return
        with self._lock:
            if 0 <= set_index < len(self._sets):
                self._sets[set_index][direction] = key
                self._save()
        self._notify()