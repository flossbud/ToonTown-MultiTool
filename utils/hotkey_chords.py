"""Pure hotkey-chord model.

Canonical string form: lowercase modifiers in FIXED order
(ctrl, alt, shift, super) joined with '+', then ONE or TWO keys SORTED
ascending ('shift+1+t', never 'shift+t+1'). A key is a lowercase
letter/digit, an F-key ('F1'..'F35'), or an X keysym name (e.g.
'KP_Add'). Stored verbatim in settings; parsed everywhere else.
A multi-key chord means all its keys are HELD TOGETHER with the
modifiers (either press order).

Guardrail (spec): a chord with NO modifier is only legal as a SINGLE
bare F-key - a bare letter/digit grab would consume that key
system-wide in every X app, and multi-key chords always need a
modifier.
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
    keys: frozenset

    @property
    def key(self) -> str:
        """Legacy single-key accessor. Raises on multi-key chords so a
        consumer that has not grown held-set matching can never silently
        mis-handle one."""
        if len(self.keys) == 1:
            return next(iter(self.keys))
        raise ValueError("multi-key chord has no single key")


def _is_fkey(key: str) -> bool:
    return (len(key) >= 2 and key[0] == "F" and key[1:].isdigit()
            and 1 <= int(key[1:]) <= 35)


def _canon_key(key: str) -> str:
    if _is_fkey(key.upper()) and len(key) >= 2:
        return key.upper()
    if len(key) == 1:
        return key.lower()
    # multi-char non-F keys (keysym names like KP_Add) pass through verbatim
    return key


def parse_chord(text: str) -> Chord:
    """Parse a chord string (case-tolerant, part-order-insensitive).
    Raises ValueError on garbage."""
    parts = [p.strip() for p in str(text).split("+")]
    if not parts or any(not p for p in parts):
        raise ValueError(f"malformed chord: {text!r}")
    canon_mods, canon_keys = set(), []
    for part in parts:
        if part.lower() in _MOD_ORDER:
            canon_mods.add(part.lower())
            continue
        key = _canon_key(part)
        if key in canon_keys:
            raise ValueError(f"duplicate key {key!r} in {text!r}")
        canon_keys.append(key)
    if not canon_keys:
        raise ValueError(f"chord has no key, only modifiers: {text!r}")
    if len(canon_keys) > 2:
        raise ValueError(f"chord has more than two keys: {text!r}")
    return Chord(mods=frozenset(canon_mods), keys=frozenset(canon_keys))


def format_chord(chord: Chord) -> str:
    mods = [m for m in _MOD_ORDER if m in chord.mods]
    return "+".join(mods + sorted(chord.keys))


def chord_error(chord: Chord) -> str | None:
    """None if the chord is bindable; else a human-readable refusal."""
    if not chord.mods and not (len(chord.keys) == 1
                               and _is_fkey(next(iter(chord.keys)))):
        return ("needs a modifier (Ctrl/Alt/Shift/Super) - a bare key would "
                "be consumed system-wide; only single F-keys may bind alone")
    return None


def x_modmask(chord: Chord) -> int:
    """The exact X modifier mask this chord grabs under."""
    mask = 0
    for m in chord.mods:
        mask |= MOD_MASKS[m]
    return mask
