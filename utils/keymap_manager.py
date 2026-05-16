"""
Keymap Manager — stores and translates per-game movement/action sets.

Persisted at ~/.config/toontown_multitool/keymaps.json as:

    {
      "version": 2,
      "ttr": [ {name, forward, reverse, left, right, jump, book, gags, tasks, map}, ... ],
      "cc":  [ {name, forward, reverse, left, right, jump, book, gags, tasks, map, sprint}, ... ]
    }

Set 0 of each game ("Default") represents both what the user physically presses
when that game is foregrounded AND what that game's client expects to receive.
Alternate sets define alternate per-toon client configurations.

Migration: a top-level list (legacy v1) is detected at load and rewritten as v2
with the list moved into the `ttr` bucket (with up->forward, down->reverse rename)
and a default CC bucket seeded from LogicalActionRegistry.
"""

from __future__ import annotations

import os
import json
import threading

from utils import logical_actions

GAMES = ("ttr", "cc")


def _seed_default_set(game: str) -> dict:
    """Build a fresh Default set for a game from the registry."""
    s = {"name": "Default"}
    for action in logical_actions.actions_for(game):
        k = logical_actions.default_key(game, action)
        if k is not None:
            s[action] = k
    return s


class KeymapManager:
    MAX_SETS_PER_GAME = 8

    def __init__(self):
        from utils.build_flavor import config_dir as _config_dir
        config_dir = _config_dir()
        os.makedirs(config_dir, exist_ok=True)
        os.chmod(config_dir, 0o700)
        self._path = os.path.join(config_dir, "keymaps.json")
        self._lock = threading.Lock()
        self._listeners = []
        self._sets: dict[str, list[dict]] = {"ttr": [], "cc": []}
        self._load()

    # ── Persistence ────────────────────────────────────────────────────────

    def _load(self):
        if not os.path.exists(self._path):
            self._sets = {"ttr": [_seed_default_set("ttr")],
                          "cc": [_seed_default_set("cc")]}
            self._save()
            return

        try:
            with open(self._path, "r") as f:
                data = json.load(f)
        except Exception as e:
            print(f"[KeymapManager] Failed to load keymaps: {e}")
            self._sets = {"ttr": [_seed_default_set("ttr")],
                          "cc": [_seed_default_set("cc")]}
            self._save()
            return

        # v1 detection: top-level list
        if isinstance(data, list):
            print("[KeymapManager] Migrating v1 keymaps.json to v2")
            self._sets = self._migrate_v1_list(data)
            self._save()
            return

        # v2
        if isinstance(data, dict) and data.get("version") == 2:
            ttr = data.get("ttr") or [_seed_default_set("ttr")]
            cc = data.get("cc") or [_seed_default_set("cc")]
            self._sets = {"ttr": ttr, "cc": cc}
            if self._backfill_missing_actions():
                self._save()
            return

        # Unrecognized — reset.
        print("[KeymapManager] Unrecognized keymaps.json shape; resetting")
        self._sets = {"ttr": [_seed_default_set("ttr")],
                      "cc": [_seed_default_set("cc")]}
        self._save()

    @staticmethod
    def _migrate_v1_list(legacy: list) -> dict[str, list[dict]]:
        """Convert v1 list-of-sets into v2 {ttr, cc} with up->forward, down->reverse rename."""
        ttr_sets: list[dict] = []
        for entry in legacy:
            if not isinstance(entry, dict):
                continue
            renamed = {}
            for k, v in entry.items():
                if k == "up":
                    renamed["forward"] = v
                elif k == "down":
                    renamed["reverse"] = v
                else:
                    renamed[k] = v
            ttr_sets.append(renamed)
        if not ttr_sets:
            ttr_sets = [_seed_default_set("ttr")]
        # Backfill any missing TTR actions from defaults
        for s in ttr_sets:
            for action in logical_actions.actions_for("ttr"):
                if action not in s:
                    s[action] = logical_actions.default_key("ttr", action) or ""
        return {"ttr": ttr_sets, "cc": [_seed_default_set("cc")]}

    def _backfill_missing_actions(self) -> bool:
        """Ensure every set has every action key. Returns True if anything changed."""
        changed = False
        for game in GAMES:
            sets = self._sets.get(game, [])
            for i, s in enumerate(sets):
                for action in logical_actions.actions_for(game):
                    if action in s:
                        continue
                    if i == 0:
                        fallback = logical_actions.default_key(game, action) or ""
                    else:
                        fallback = sets[0].get(action, "")
                    s[action] = fallback
                    changed = True
        return changed

    def _save(self):
        try:
            with open(self._path, "w") as f:
                json.dump({"version": 2, "ttr": self._sets["ttr"], "cc": self._sets["cc"]}, f, indent=2)
                f.flush()
        except Exception as e:
            print(f"[KeymapManager] Failed to save keymaps: {e}")

    # ── Change notification ────────────────────────────────────────────────

    def on_change(self, callback):
        with self._lock:
            self._listeners.append(callback)

    def _notify(self):
        with self._lock:
            listeners = list(self._listeners)
        for cb in listeners:
            try:
                cb()
            except Exception as e:
                print(f"[KeymapManager] Listener error: {e}")

    # ── Read API ───────────────────────────────────────────────────────────

    def get_sets(self, game: str) -> list:
        with self._lock:
            return [dict(s) for s in self._sets.get(game, [])]

    def get_set(self, game: str, index: int) -> dict | None:
        with self._lock:
            sets = self._sets.get(game, [])
            if 0 <= index < len(sets):
                return dict(sets[index])
            return None

    def get_default(self, game: str) -> dict:
        with self._lock:
            sets = self._sets.get(game, [])
            return dict(sets[0]) if sets else {}

    def get_set_names(self, game: str) -> list:
        with self._lock:
            return [s.get("name", f"Set {i+1}") for i, s in enumerate(self._sets.get(game, []))]

    def num_sets(self, game: str) -> int:
        with self._lock:
            return len(self._sets.get(game, []))

    def get_action_in_set(self, game: str, set_index: int, key: str) -> str | None:
        with self._lock:
            sets = self._sets.get(game, [])
            if not (0 <= set_index < len(sets)):
                return None
            s = sets[set_index]
            for action in logical_actions.actions_for(game):
                if s.get(action) == key:
                    return action
            return None

    def get_key_for_action(self, game: str, set_index: int, action: str) -> str | None:
        with self._lock:
            sets = self._sets.get(game, [])
            if not (0 <= set_index < len(sets)):
                return None
            return sets[set_index].get(action)

    def get_all_keys(self) -> frozenset:
        """Union of every action's bound key across both games and all sets."""
        with self._lock:
            keys = set()
            for game in GAMES:
                for s in self._sets.get(game, []):
                    for action in logical_actions.actions_for(game):
                        k = s.get(action)
                        if k:
                            keys.add(k)
            return frozenset(keys)

    def get_default_keys(self, game: str) -> frozenset:
        """The set of keys bound in this game's Default set."""
        with self._lock:
            sets = self._sets.get(game, [])
            if not sets:
                return frozenset()
            s = sets[0]
            return frozenset(v for a in logical_actions.actions_for(game) if (v := s.get(a)))

    # ── Write API (Task 4 expands this further) ────────────────────────────

    def update_set_key(self, game: str, set_index: int, action: str, key: str):
        if game not in GAMES:
            return
        if not logical_actions.supports(game, action):
            return
        with self._lock:
            sets = self._sets.get(game, [])
            if 0 <= set_index < len(sets):
                sets[set_index][action] = key
                self._save()
        self._notify()
