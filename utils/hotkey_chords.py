"""Pure hotkey-chord model.

Canonical string form: lowercase modifiers in FIXED order
(ctrl, alt, shift, super) joined with '+', then exactly one key: a
lowercase letter/digit, an F-key ('F1'..'F35'), or an X keysym name
(e.g. 'KP_Add'). Stored verbatim in settings; parsed everywhere else.

Guardrail (spec): a chord with NO modifier is only legal for F-keys - a
bare letter/digit grab would consume that key system-wide in every X app.
"""
from __future__ import annotations

from dataclasses import dataclass

_MOD_ORDER = ("ctrl", "alt", "shift", "super")

# X modifier masks by canonical mod name (values match Xlib.X constants;
# kept literal so this module stays importable without python-xlib).
MOD_MASKS = {"shift": 1 << 0, "ctrl": 1 << 2, "alt": 1 << 3, "super": 1 << 6}


@dataclass(frozen=True)
class Chord:
    mods: frozenset
    key: str


def _is_fkey(key: str) -> bool:
    return (len(key) >= 2 and key[0] == "F" and key[1:].isdigit()
            and 1 <= int(key[1:]) <= 35)


def parse_chord(text: str) -> Chord:
    """Parse a chord string (case-tolerant). Raises ValueError on garbage."""
    parts = [p.strip() for p in str(text).split("+")]
    if not parts or any(not p for p in parts):
        raise ValueError(f"malformed chord: {text!r}")
    *mods, key = parts
    canon_mods = set()
    for m in mods:
        m = m.lower()
        if m not in _MOD_ORDER:
            raise ValueError(f"unknown modifier {m!r} in {text!r}")
        canon_mods.add(m)
    if key.lower() in _MOD_ORDER:
        raise ValueError(f"chord has no key, only modifiers: {text!r}")
    if _is_fkey(key.upper()) and len(key) >= 2:
        key = key.upper()
    elif len(key) == 1:
        key = key.lower()
    # multi-char non-F keys (keysym names like KP_Add) pass through verbatim
    return Chord(mods=frozenset(canon_mods), key=key)


def format_chord(chord: Chord) -> str:
    mods = [m for m in _MOD_ORDER if m in chord.mods]
    return "+".join(mods + [chord.key])


def chord_error(chord: Chord) -> str | None:
    """None if the chord is bindable; else a human-readable refusal."""
    if not chord.mods and not _is_fkey(chord.key):
        return ("needs a modifier (Ctrl/Alt/Shift/Super) - a bare key would "
                "be consumed system-wide; only F-keys may bind alone")
    return None


def x_modmask(chord: Chord) -> int:
    """The exact X modifier mask this chord grabs under."""
    mask = 0
    for m in chord.mods:
        mask |= MOD_MASKS[m]
    return mask
