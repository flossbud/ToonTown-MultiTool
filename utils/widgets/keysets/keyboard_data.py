"""Visual-keyboard layout + key ABI helpers. Pure Python (no Qt).

Keycap CODES are the canonical key names from utils.key_registry (the storage
ABI used by keymap_manager / MovementKeyField): letters lowercase ("w"),
"space", arrows "Up"/"Down"/..., modifiers "Shift_L"/"Alt_R"/..., "BackSpace"/
"Return"/"Delete", digits/punctuation as their literal char. LABELS are the
printed cap text. Match a set value against a keycap code directly.
"""
from __future__ import annotations

# Actions that read as "movement" (bright accent) on the board. logical_actions
# has no such split; this mirrors the tuple hardcoded in the old SetCard.
MOVEMENT_ACTIONS = ("forward", "reverse", "left", "right", "jump")

# (code, label, width_units). None = spacer (nav cluster only).
KEY_ROWS = [
    [("`", "`", 1), ("1", "1", 1), ("2", "2", 1), ("3", "3", 1), ("4", "4", 1),
     ("5", "5", 1), ("6", "6", 1), ("7", "7", 1), ("8", "8", 1), ("9", "9", 1),
     ("0", "0", 1), ("-", "-", 1), ("=", "=", 1), ("BackSpace", "Backspace", 2)],
    [("Tab", "Tab", 1.5), ("q", "Q", 1), ("w", "W", 1), ("e", "E", 1),
     ("r", "R", 1), ("t", "T", 1), ("y", "Y", 1), ("u", "U", 1), ("i", "I", 1),
     ("o", "O", 1), ("p", "P", 1), ("[", "[", 1), ("]", "]", 1), ("\\", "\\", 1.5)],
    [("Caps", "Caps", 1.75), ("a", "A", 1), ("s", "S", 1), ("d", "D", 1),
     ("f", "F", 1), ("g", "G", 1), ("h", "H", 1), ("j", "J", 1), ("k", "K", 1),
     ("l", "L", 1), (";", ";", 1), ("'", "'", 1), ("Return", "Enter", 2.25)],
    [("Shift_L", "Shift", 2.25), ("z", "Z", 1), ("x", "X", 1), ("c", "C", 1),
     ("v", "V", 1), ("b", "B", 1), ("n", "N", 1), ("m", "M", 1), (",", ",", 1),
     (".", ".", 1), ("/", "/", 1), ("Shift_R", "Shift", 2.25)],
    [("Control_L", "Ctrl", 1.5), ("Alt_L", "Alt", 1.5), ("space", "Space", 7),
     ("Alt_R", "Alt", 1.5), ("Control_R", "Ctrl", 1.5)],
]

NAV_ROWS = [
    [("Delete", "Del", 1), ("End", "End", 1), ("Next", "PgDn", 1)],
    [None, ("Up", "▲", 1), None],
    [("Left", "◀", 1), ("Down", "▼", 1), ("Right", "▶", 1)],
]

# Mac bottom modifier row. Meta_* are decorative (Cmd is not an assignable
# canonical), so they never match a stored value.
MAC_BOTTOM_ROW = [
    ("Control_L", "⌃", 1.3), ("Alt_L", "⌥", 1.3), ("Meta_L", "⌘", 1.5),
    ("space", "Space", 6.1), ("Meta_R", "⌘", 1.5), ("Alt_R", "⌥", 1.3),
]

# Mac printed labels for physical keys, keyed by canonical code.
MAC_KEY_LABELS = {
    "BackSpace": "⌫", "Return": "return", "Caps": "⇪", "Tab": "⇥",
    "Shift_L": "⇧", "Shift_R": "⇧", "Delete": "⌦",
}

# Mac displayed VALUE strings for assigned modifier keys.
MAC_VALUE_LABELS = {
    "Shift_L": "⇧ Shift", "Shift_R": "⇧ Shift",
    "Alt_L": "⌥ Option", "Alt_R": "⌥ Option",
    "Control_L": "⌃ Control", "Control_R": "⌃ Control",
    "BackSpace": "⌫ Delete", "Delete": "⌦ Fwd Del",
}


def is_movement(action: str) -> bool:
    return action in MOVEMENT_ACTIONS


def assignment_map(set_dict: dict, actions) -> dict:
    """{key_value: action} for the given actions (last write wins on dup)."""
    m = {}
    for a in actions:
        v = set_dict.get(a)
        if v:
            m[v] = a
    return m


def conflict_values(set_dict: dict, actions) -> set:
    """Set of key values assigned to more than one action within the set."""
    by_val: dict = {}
    for a in actions:
        v = set_dict.get(a)
        if not v:
            continue
        by_val.setdefault(v, []).append(a)
    return {v for v, ks in by_val.items() if len(ks) > 1}


def rows_for(mac: bool):
    """Main-block rows; on mac the bottom modifier row is swapped."""
    if not mac:
        return list(KEY_ROWS)
    return list(KEY_ROWS[:-1]) + [MAC_BOTTOM_ROW]


def key_label(code: str, default: str, mac: bool) -> str:
    return MAC_KEY_LABELS.get(code, default) if mac else default


def value_label(value: str, mac: bool) -> str:
    if not mac or not value:
        return value
    return MAC_VALUE_LABELS.get(value, value)
