"""X11 keysym <-> macOS CGKeyCode + modifier-flag translation.

The single translation table the macOS input backend uses. The rest of the
app speaks X11 keysym strings ("w", "Up", "Return", "Shift_L"); macOS
``CGEventCreateKeyboardEvent`` needs an ANSI ``CGKeyCode`` and, for held
modifiers, a ``CGEventFlags`` bitmask.

Pure data + lookups: NO PyObjC import. The flag constants below are the literal
``kCGEventFlagMask*`` integer values from ``<CoreGraphics/CGEventTypes.h>`` so
this module imports and unit-tests cleanly on any interpreter, including the
non-mac-typed one CI runs on.

CGKeyCode values are the ANSI virtual key codes from ``<HIToolbox/Events.h>``
(the ``kVK_*`` constants). They are physical-position codes, so a US-ANSI
layout is assumed; that matches what the game cares about (WASD position, the
arrows, the number row, the numpad).

Modifiers appear in BOTH directions: ``input_service._send_modifier_to_bg()``
posts modifiers AS KEYS (key-down/key-up of e.g. Shift_L), so every modifier
needs a CGKeyCode entry; modifiers held while another key is posted are folded
in as event flags, so they also need a flag entry.
"""

from __future__ import annotations

from typing import Iterable, Optional


# ── CGEventFlags (literal kCGEventFlagMask* values; no PyObjC needed) ────────

FLAG_SHIFT = 0x00020000      # kCGEventFlagMaskShift
FLAG_CONTROL = 0x00040000    # kCGEventFlagMaskControl
FLAG_OPTION = 0x00080000     # kCGEventFlagMaskAlternate (Option / Alt)
FLAG_COMMAND = 0x00100000    # kCGEventFlagMaskCommand


# ── keysym -> CGKeyCode ─────────────────────────────────────────────────────
# Insertion order matters: keysym_for_cgkeycode() is first-wins, so the
# canonical X11 keysym for each physical key is listed before any alias that
# shares the same CGKeyCode (e.g. "Prior" before "Page_Up").

CGKEYCODE_FOR_KEYSYM: dict[str, int] = {
    # ── Letters (stored lowercase; lookup is case-insensitive for 1-char) ──
    "a": 0x00, "s": 0x01, "d": 0x02, "f": 0x03, "h": 0x04, "g": 0x05,
    "z": 0x06, "x": 0x07, "c": 0x08, "v": 0x09, "b": 0x0B, "q": 0x0C,
    "w": 0x0D, "e": 0x0E, "r": 0x0F, "y": 0x10, "t": 0x11, "o": 0x1F,
    "u": 0x20, "i": 0x22, "p": 0x23, "l": 0x25, "j": 0x26, "k": 0x28,
    "n": 0x2D, "m": 0x2E,

    # ── Digit row ──
    "1": 0x12, "2": 0x13, "3": 0x14, "4": 0x15, "5": 0x17,
    "6": 0x16, "7": 0x1A, "8": 0x1C, "9": 0x19, "0": 0x1D,

    # ── Control / whitespace ──
    "space": 0x31,
    "Return": 0x24,
    "Tab": 0x30,
    "BackSpace": 0x33,    # delete-left
    "Escape": 0x35,
    "Delete": 0x75,       # forward delete

    # ── Arrows ──
    "Up": 0x7E, "Down": 0x7D, "Left": 0x7B, "Right": 0x7C,

    # ── Navigation cluster ──
    "Home": 0x73,
    "End": 0x77,
    "Prior": 0x74,        # Page Up (canonical X11 keysym)
    "Next": 0x79,         # Page Down (canonical X11 keysym)
    "Insert": 0x72,       # kVK_Help occupies the Insert position
    # Aliases (after canonical entries so reverse lookup prefers Prior/Next):
    "Page_Up": 0x74,
    "Page_Down": 0x79,

    # ── Function keys ──
    "F1": 0x7A, "F2": 0x78, "F3": 0x63, "F4": 0x76, "F5": 0x60, "F6": 0x61,
    "F7": 0x62, "F8": 0x64, "F9": 0x65, "F10": 0x6D, "F11": 0x67, "F12": 0x6F,

    # ── Numpad ──
    "KP_0": 0x52, "KP_1": 0x53, "KP_2": 0x54, "KP_3": 0x55, "KP_4": 0x56,
    "KP_5": 0x57, "KP_6": 0x58, "KP_7": 0x59, "KP_8": 0x5B, "KP_9": 0x5C,
    "KP_Decimal": 0x41,
    "KP_Enter": 0x4C,
    "KP_Add": 0x45,
    "KP_Subtract": 0x4E,
    "KP_Multiply": 0x43,
    "KP_Divide": 0x4B,

    # ── Punctuation (X11 keysym names) ──
    "minus": 0x1B,
    "equal": 0x18,
    "bracketleft": 0x21,
    "bracketright": 0x1E,
    "semicolon": 0x29,
    "apostrophe": 0x27,
    "comma": 0x2B,
    "period": 0x2F,
    "slash": 0x2C,
    "backslash": 0x2A,
    "grave": 0x32,

    # ── Modifiers (posted as keys by _send_modifier_to_bg) ──
    "Shift_L": 0x38, "Shift_R": 0x3C,
    "Control_L": 0x3B, "Control_R": 0x3E,
    "Alt_L": 0x3A, "Alt_R": 0x3D,
}


# ── modifier keysym -> CGEventFlag ──────────────────────────────────────────

FLAG_FOR_MODIFIER_KEYSYM: dict[str, int] = {
    "Shift_L": FLAG_SHIFT,
    "Shift_R": FLAG_SHIFT,
    "Control_L": FLAG_CONTROL,
    "Control_R": FLAG_CONTROL,
    "Alt_L": FLAG_OPTION,
    "Alt_R": FLAG_OPTION,
    # X11 also surfaces these synonyms; macOS maps Alt->Option, Super/Win->Cmd.
    "Meta": FLAG_OPTION,
    "Meta_L": FLAG_OPTION,
    "Meta_R": FLAG_OPTION,
    "Super": FLAG_COMMAND,
    "Super_L": FLAG_COMMAND,
    "Super_R": FLAG_COMMAND,
}


# Reverse map built once, first-wins so canonical keysyms shadow aliases.
_KEYSYM_FOR_CGKEYCODE: dict[int, str] = {}
for _sym, _vk in CGKEYCODE_FOR_KEYSYM.items():
    _KEYSYM_FOR_CGKEYCODE.setdefault(_vk, _sym)
del _sym, _vk


# Registry keysyms with no ANSI CGKeyCode. Currently every primary keysym in
# NAMED_KEY_REGISTRY (modifiers, control keys, arrows, F1-F12, navigation
# cluster, numpad) maps to a code above, so this is empty. It exists so the
# contract test documents any future gap explicitly instead of silently
# dropping a key.
UNSUPPORTED_KEYSYMS: frozenset = frozenset()


def cgkeycode_for_keysym(keysym: str) -> Optional[int]:
    """Return the ANSI CGKeyCode for an X11 keysym, or None if unmapped.

    Named keys ("Up", "Return", "Shift_L") match as-given. Single characters
    ("w"/"W", "1") match case-insensitively.
    """
    if not keysym:
        return None
    vk = CGKEYCODE_FOR_KEYSYM.get(keysym)
    if vk is not None:
        return vk
    if len(keysym) == 1:
        return CGKEYCODE_FOR_KEYSYM.get(keysym.lower())
    return None


def keysym_for_cgkeycode(vk: int) -> Optional[str]:
    """Return the canonical X11 keysym for a CGKeyCode, or None (first-wins)."""
    return _KEYSYM_FOR_CGKEYCODE.get(vk)


def flag_for_modifier_keysym(keysym: str) -> Optional[int]:
    """Return the CGEventFlag for a modifier keysym, or None if not a modifier."""
    if not keysym:
        return None
    return FLAG_FOR_MODIFIER_KEYSYM.get(keysym)


def flags_for_modifiers(modifiers: Optional[Iterable[str]]) -> int:
    """OR together the CGEventFlags for an iterable of modifier keysyms.

    None or empty -> 0. Non-modifier entries contribute nothing.
    """
    if not modifiers:
        return 0
    flags = 0
    for keysym in modifiers:
        flag = FLAG_FOR_MODIFIER_KEYSYM.get(keysym)
        if flag is not None:
            flags |= flag
    return flags
