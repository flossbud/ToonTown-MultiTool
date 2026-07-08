"""Logical action registry: the single source of truth for which actions
TTMT forwards to background toons, which games each action applies to,
and the per-game default binding.

Adding a new action: one Action(...) entry below + a label in ACTION_LABELS below.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType


# UI labels for the movement/action keys (was tabs/keymap_tab.py::ACTION_LABELS).
ACTION_LABELS = {
    "forward": "Forward", "reverse": "Reverse", "left": "Left", "right": "Right",
    "jump": "Jump", "book": "Book", "gags": "Gags", "tasks": "Tasks",
    "map": "Map", "sprint": "Sprint", "action": "Perform Action",
}


@dataclass(frozen=True)
class Action:
    games: frozenset[str]
    defaults: MappingProxyType


ACTIONS: dict[str, Action] = {
    "forward": Action(frozenset({"ttr", "cc"}), MappingProxyType({"ttr": "Up",      "cc": "w"})),
    "reverse": Action(frozenset({"ttr", "cc"}), MappingProxyType({"ttr": "Down",    "cc": "s"})),
    "left":    Action(frozenset({"ttr", "cc"}), MappingProxyType({"ttr": "Left",    "cc": "a"})),
    "right":   Action(frozenset({"ttr", "cc"}), MappingProxyType({"ttr": "Right",   "cc": "d"})),
    "jump":    Action(frozenset({"ttr", "cc"}), MappingProxyType({"ttr": "space",   "cc": "space"})),
    "book":    Action(frozenset({"ttr", "cc"}), MappingProxyType({"ttr": "Alt_L",   "cc": "Escape"})),
    "gags":    Action(frozenset({"ttr", "cc"}), MappingProxyType({"ttr": "g",       "cc": "q"})),
    "tasks":   Action(frozenset({"ttr", "cc"}), MappingProxyType({"ttr": "t",       "cc": "e"})),
    "map":     Action(frozenset({"ttr", "cc"}), MappingProxyType({"ttr": "Shift_L", "cc": "Alt_L"})),
    "sprint":  Action(frozenset({"cc"}),        MappingProxyType({"cc": "Shift_L"})),
    "action":  Action(frozenset({"ttr"}),       MappingProxyType({"ttr": "Delete"})),
}


def supports(game: str, action: str) -> bool:
    a = ACTIONS.get(action)
    return a is not None and game in a.games


def default_key(game: str, action: str) -> str | None:
    a = ACTIONS.get(action)
    return None if a is None else a.defaults.get(game)


def actions_for(game: str) -> list[str]:
    """Return action names applicable to a game, in dict-insertion order."""
    return [name for name, a in ACTIONS.items() if game in a.games]
