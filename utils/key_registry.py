"""Single source of truth for game-relevant named keys.

Every non-printable, non-char key TTMT can assign lives here once. The four
derived constants at the bottom feed the four layers that previously kept
their own hand-maintained dicts:
  - NAMED_KEYSYMS_FROM_REGISTRY  -> services/input_service.py (send-time keysym)
  - PASSTHROUGH_KEYSYMS          -> services/input_service.py (CC X11 grabber passthrough)
  - PYNPUT_NAME_MAP_BASE         -> services/hotkey_manager.py (pynput name decode)
  - DISPLAY_NAMES_FROM_REGISTRY  -> utils/widgets/keysets/movement_key_field.py (UI labels)

Pure Python by design: no Qt and no pynput imports, so service-layer and
headless code can import it without dragging in a GUI/runtime dependency.
Qt key resolution (getattr(Qt, qt_key_name)) happens in movement_key_field.py only.
"""

from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class KeyDef:
    canonical: str                       # storage ABI — used in keymaps.json / HeldKeyRegistry
    display: str                         # UI label shown in keymap tab
    keysyms: tuple[str, ...]            # X11 keysym strings for _resolve_keysym + passthrough
    pynput_names: tuple[str, ...] = ()  # pynput key.name values that normalize to this canonical
    # extra names accepted from TTR/config imports. Doc-only: NO runtime consumer
    # reads this field. May overlap pynput_names (e.g. arrows carry "up" in both);
    # harmless today, but a future task that folds import_aliases into a
    # name->canonical map must apply the same no-duplicate discipline that
    # PYNPUT_NAME_MAP_BASE relies on.
    import_aliases: tuple[str, ...] = ()
    qt_key_names: tuple[str, ...] = ()   # Qt key name strings; resolved via getattr(Qt, name) in movement_key_field.py
    numpad_key: bool = False             # True → _NUMPAD_KEYS path; False → SPECIAL_KEYS path
    category: str = "control"           # modifier/control/arrow/function/navigation/numpad
    passthrough: bool = True            # include in CC X11 grabber passthrough tuple


NAMED_KEY_REGISTRY: tuple[KeyDef, ...] = (

    # ── Modifiers ──────────────────────────────────────────────────────────
    # qt_key_names=() — captured via _side_aware_modifier_key(), not SPECIAL_KEYS

    KeyDef("Shift_L",   "L Shift", ("Shift_L",),   pynput_names=("shift_l", "shift"),  category="modifier"),
    KeyDef("Shift_R",   "R Shift", ("Shift_R",),   pynput_names=("shift_r",),           category="modifier"),
    KeyDef("Control_L", "L Ctrl",  ("Control_L",), pynput_names=("ctrl_l", "ctrl"),     category="modifier"),
    KeyDef("Control_R", "R Ctrl",  ("Control_R",), pynput_names=("ctrl_r",),            category="modifier"),
    KeyDef("Alt_L",     "L Alt",   ("Alt_L",),     pynput_names=("alt_l", "alt"),       category="modifier"),
    # "alt_gr": pynput's win32 backend resolves VK_RMENU to Key.alt_gr (it
    # shares the vk with Key.alt_r and, defined later, wins the vk->Key dict),
    # so every physical right-alt press on Windows arrives named "alt_gr".
    # On X11 layouts where right alt is AltGr (ISO_Level3_Shift) pynput also
    # reports "alt_gr" -- same physical key, same canonical.
    KeyDef("Alt_R",     "R Alt",   ("Alt_R",),     pynput_names=("alt_r", "alt_gr"),    category="modifier"),

    # ── Control keys ───────────────────────────────────────────────────────

    KeyDef("space",    "Space",    ("space",),    pynput_names=("space",),
           qt_key_names=("Key_Space",)),
    # Key_Enter intentionally appears here AND on KP_Enter below. They land in
    # different derived dicts (SPECIAL_KEYS vs _NUMPAD_KEYS), and keyPressEvent
    # checks KeypadModifier first, so numpad Enter routes to KP_Enter while this
    # Key_Enter->Return entry is the behavior-preserving fallback the pre-registry
    # SPECIAL_KEYS already had.
    KeyDef("Return",   "Enter",    ("Return",),   pynput_names=("enter",),
           import_aliases=("enter",),             qt_key_names=("Key_Return", "Key_Enter")),
    KeyDef("Tab",      "Tab",      ("Tab",),      pynput_names=("tab",),
           qt_key_names=("Key_Tab",)),
    KeyDef("BackSpace","Backspace",("BackSpace",),pynput_names=("backspace",),
           qt_key_names=("Key_Backspace",)),
    KeyDef("Escape",   "Esc",      ("Escape",),   pynput_names=("esc",),
           import_aliases=("escape",),            qt_key_names=("Key_Escape",)),
    KeyDef("Delete",   "Delete",   ("Delete",),   pynput_names=("delete",),
           qt_key_names=("Key_Delete",)),

    # ── Arrow keys ─────────────────────────────────────────────────────────

    KeyDef("Up",    "Up Arrow",    ("Up",),    pynput_names=("up",),
           import_aliases=("arrow_up", "up"),    qt_key_names=("Key_Up",),    category="arrow"),
    KeyDef("Down",  "Down Arrow",  ("Down",),  pynput_names=("down",),
           import_aliases=("arrow_down", "down"),qt_key_names=("Key_Down",),  category="arrow"),
    KeyDef("Left",  "Left Arrow",  ("Left",),  pynput_names=("left",),
           import_aliases=("arrow_left", "left"),qt_key_names=("Key_Left",),  category="arrow"),
    KeyDef("Right", "Right Arrow", ("Right",), pynput_names=("right",),
           import_aliases=("arrow_right","right"),qt_key_names=("Key_Right",),category="arrow"),

    # ── Function keys F1-F12 ───────────────────────────────────────────────
    # Previously missing from SPECIAL_KEYS: users could not assign them via UI.
    # Already present in NAMED_KEYSYMS, so send-time was working for imported configs.

    KeyDef("F1",  "F1",  ("F1",),  pynput_names=("f1",),  qt_key_names=("Key_F1",),  category="function"),
    KeyDef("F2",  "F2",  ("F2",),  pynput_names=("f2",),  qt_key_names=("Key_F2",),  category="function"),
    KeyDef("F3",  "F3",  ("F3",),  pynput_names=("f3",),  qt_key_names=("Key_F3",),  category="function"),
    KeyDef("F4",  "F4",  ("F4",),  pynput_names=("f4",),  qt_key_names=("Key_F4",),  category="function"),
    KeyDef("F5",  "F5",  ("F5",),  pynput_names=("f5",),  qt_key_names=("Key_F5",),  category="function"),
    KeyDef("F6",  "F6",  ("F6",),  pynput_names=("f6",),  qt_key_names=("Key_F6",),  category="function"),
    KeyDef("F7",  "F7",  ("F7",),  pynput_names=("f7",),  qt_key_names=("Key_F7",),  category="function"),
    KeyDef("F8",  "F8",  ("F8",),  pynput_names=("f8",),  qt_key_names=("Key_F8",),  category="function"),
    KeyDef("F9",  "F9",  ("F9",),  pynput_names=("f9",),  qt_key_names=("Key_F9",),  category="function"),
    KeyDef("F10", "F10", ("F10",), pynput_names=("f10",), qt_key_names=("Key_F10",), category="function"),
    KeyDef("F11", "F11", ("F11",), pynput_names=("f11",), qt_key_names=("Key_F11",), category="function"),
    KeyDef("F12", "F12", ("F12",), pynput_names=("f12",), qt_key_names=("Key_F12",), category="function"),

    # ── Navigation cluster ─────────────────────────────────────────────────
    # Previously missing from BOTH SPECIAL_KEYS and NAMED_KEYSYMS.
    # Prior/Next are the correct X11 keysym names for PageUp/PageDown.

    KeyDef("Home",   "Home",   ("Home",),   pynput_names=("home",),
           qt_key_names=("Key_Home",),    category="navigation"),
    KeyDef("End",    "End",    ("End",),    pynput_names=("end",),
           qt_key_names=("Key_End",),     category="navigation"),
    KeyDef("Prior",  "PgUp",   ("Prior",),  pynput_names=("page_up",),
           import_aliases=("page_up",),   qt_key_names=("Key_PageUp",),  category="navigation"),
    KeyDef("Next",   "PgDn",   ("Next",),   pynput_names=("page_down",),
           import_aliases=("page_down",), qt_key_names=("Key_PageDown",),category="navigation"),
    KeyDef("Insert", "Insert", ("Insert",), pynput_names=("insert",),
           qt_key_names=("Key_Insert",),  category="navigation"),

    # ── Numpad ─────────────────────────────────────────────────────────────
    # qt_key_names has TWO entries per digit key:
    #   [0] NumLock ON  → Qt.Key_<digit>   e.g. Key_0
    #   [1] NumLock OFF → Qt.Key_<nav>     e.g. Key_Insert
    # Both map to the same canonical so the key is always capturable.
    # KP_5 NumLock-off uses Qt.Key_Clear (XK_Clear in X11).

    KeyDef("KP_0",      "NP 0",    ("KP_0",),
           qt_key_names=("Key_0",   "Key_Insert"),    numpad_key=True, category="numpad"),
    KeyDef("KP_1",      "NP 1",    ("KP_1",),
           qt_key_names=("Key_1",   "Key_End"),       numpad_key=True, category="numpad"),
    KeyDef("KP_2",      "NP 2",    ("KP_2",),
           qt_key_names=("Key_2",   "Key_Down"),      numpad_key=True, category="numpad"),
    KeyDef("KP_3",      "NP 3",    ("KP_3",),
           qt_key_names=("Key_3",   "Key_PageDown"),  numpad_key=True, category="numpad"),
    KeyDef("KP_4",      "NP 4",    ("KP_4",),
           qt_key_names=("Key_4",   "Key_Left"),      numpad_key=True, category="numpad"),
    KeyDef("KP_5",      "NP 5",    ("KP_5",),
           qt_key_names=("Key_5",   "Key_Clear"),     numpad_key=True, category="numpad"),
    KeyDef("KP_6",      "NP 6",    ("KP_6",),
           qt_key_names=("Key_6",   "Key_Right"),     numpad_key=True, category="numpad"),
    KeyDef("KP_7",      "NP 7",    ("KP_7",),
           qt_key_names=("Key_7",   "Key_Home"),      numpad_key=True, category="numpad"),
    KeyDef("KP_8",      "NP 8",    ("KP_8",),
           qt_key_names=("Key_8",   "Key_Up"),        numpad_key=True, category="numpad"),
    KeyDef("KP_9",      "NP 9",    ("KP_9",),
           qt_key_names=("Key_9",   "Key_PageUp"),    numpad_key=True, category="numpad"),
    KeyDef("KP_Decimal","NP .",    ("KP_Decimal",),
           qt_key_names=("Key_Period","Key_Delete"),  numpad_key=True, category="numpad"),
    KeyDef("KP_Enter",  "NP Enter",("KP_Enter",),
           qt_key_names=("Key_Enter",),               numpad_key=True, category="numpad"),
    KeyDef("KP_Add",    "NP +",    ("KP_Add",),
           qt_key_names=("Key_Plus",),                numpad_key=True, category="numpad"),
    KeyDef("KP_Subtract","NP -",   ("KP_Subtract",),
           qt_key_names=("Key_Minus",),               numpad_key=True, category="numpad"),
    KeyDef("KP_Multiply","NP *",   ("KP_Multiply",),
           qt_key_names=("Key_Asterisk",),            numpad_key=True, category="numpad"),
    KeyDef("KP_Divide", "NP /",    ("KP_Divide",),
           qt_key_names=("Key_Slash",),               numpad_key=True, category="numpad"),
)


# ── Derived constants consumed by other modules ────────────────────────────

# {canonical: first_keysym} — alias target for NAMED_KEYSYMS in input_service.py
NAMED_KEYSYMS_FROM_REGISTRY: dict[str, str] = {
    kd.canonical: kd.keysyms[0] for kd in NAMED_KEY_REGISTRY
}

# Flat tuple of all keysyms for passthrough=True entries; deduped, stable order.
# Replaces the hardcoded modifiers+common tuple in _passthrough_keysyms_for_canonical.
# letters (a-z) and digits (0-9) remain inline in that function.
PASSTHROUGH_KEYSYMS: tuple[str, ...] = tuple(dict.fromkeys(
    sym for kd in NAMED_KEY_REGISTRY if kd.passthrough for sym in kd.keysyms
))

# {pynput_name: canonical} — base for PYNPUT_NAME_MAP in hotkey_manager.py
PYNPUT_NAME_MAP_BASE: dict[str, str] = {
    name: kd.canonical
    for kd in NAMED_KEY_REGISTRY
    for name in kd.pynput_names
}

# {canonical: display} — feeds DISPLAY_NAMES in utils/widgets/keysets/movement_key_field.py
DISPLAY_NAMES_FROM_REGISTRY: dict[str, str] = {
    kd.canonical: kd.display for kd in NAMED_KEY_REGISTRY
}
