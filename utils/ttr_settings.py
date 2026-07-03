"""TTR settings.json reader. Resolves the keymap and the effective chat-by-typing
state per the v2.1.3-a chat-block-rule design.

Locations checked, in order:
  - explicit engine_dir from app settings_manager (passed in by the caller)
  - $APPDATA/Toontown Rewritten/settings.json  (Windows native)
  - find_engine_path() result + 'settings.json'  (Linux native, via ttr_login_service)
  - ~/.var/app/com.toontownrewritten.Launcher/data/settings.json  (Linux Flatpak)
"""
from __future__ import annotations

import json
import os
import string
from dataclasses import dataclass
from pathlib import Path

# Legacy top-level field names guessed for the chat-by-typing toggle before a
# real settings.json was probed. The REAL field on a live install is nested:
# controls["automatic-chat-input"] (confirmed by reading
# C:\Program Files (x86)\Toontown Rewritten\settings.json on the Windows test
# box). These names are kept as a fallback for older/other client versions.
_CHAT_BY_TYPING_FIELDS: tuple[str, ...] = (
    "chat-by-typing", "chatByTyping", "enableChatByTyping", "typingChat",
)

# Stock chat-open chords per a clean TTR install: controls["chat"]="enter",
# controls["groupChat"]="alt-enter". Used whenever a chord value is missing
# or unparseable.
_DEFAULT_CHAT_OPEN_CHORDS: tuple = (
    (frozenset(), "Return"),
    (frozenset({"alt"}), "Return"),
)

# Modifier tokens TTR may emit in chord strings, normalized for TTMT.
_CHORD_MOD_NORMALIZE = {
    "alt": "alt", "ctrl": "ctrl", "control": "ctrl", "shift": "shift",
}

_FLATPAK_PATH = os.path.expanduser(
    "~/.var/app/com.toontownrewritten.Launcher/data/settings.json"
)

# Native macOS TTR client writes settings.json under Application Support.
_MACOS_PATH = os.path.expanduser(
    "~/Library/Application Support/Toontown Rewritten/settings.json"
)


def _engine_dir_from_settings():
    """Hook for callers / tests to inject the discovered engine dir.

    Returns None at module scope; B.3's main.py wiring will pass an explicit
    engine_dir to locate_settings_file() instead. Tests monkeypatch this to
    isolate path discovery."""
    return None


@dataclass
class TtrSettings:
    controls: dict
    chat_by_typing_enabled_resolved: bool
    has_letter_hotkeys: bool
    source_path: Path | None = None
    # (modifiers, keysym) pairs that open the chat input, parsed from
    # controls["chat"] / controls["groupChat"]. Defaults to enter / alt-enter.
    chat_open_chords: tuple[tuple[frozenset[str], str], ...] = _DEFAULT_CHAT_OPEN_CHORDS


def locate_settings_file(engine_dir: str | None = None) -> Path | None:
    candidates: list[Path] = []
    if engine_dir:
        candidates.append(Path(engine_dir) / "settings.json")
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.append(Path(appdata) / "Toontown Rewritten" / "settings.json")
    discovered = _engine_dir_from_settings()
    if discovered:
        candidates.append(Path(discovered) / "settings.json")
    candidates.append(Path(_FLATPAK_PATH))
    candidates.append(Path(_MACOS_PATH))
    for c in candidates:
        if c.exists():
            return c
    return None


def parse_ttr_settings(path: Path | str) -> TtrSettings:
    p = Path(path)
    data = json.loads(p.read_text())
    controls = dict(data.get("controls", {}))
    has_letter = _has_letter_hotkeys(controls)
    explicit = _explicit_chat_flag(data)
    if explicit is not None:
        resolved = explicit
    else:
        resolved = not has_letter
    return TtrSettings(
        controls=controls,
        chat_by_typing_enabled_resolved=resolved,
        has_letter_hotkeys=has_letter,
        source_path=p,
        chat_open_chords=_resolve_chat_open_chords(controls),
    )


def _has_letter_hotkeys(controls: dict) -> bool:
    for v in controls.values():
        if isinstance(v, str) and len(v) == 1 and v.lower() in string.ascii_lowercase:
            return True
    return False


def _explicit_chat_flag(data: dict) -> bool | None:
    # Real field first: nested under controls, and only a genuine JSON bool
    # counts (any other type is treated as absent, not coerced).
    controls = data.get("controls")
    if isinstance(controls, dict):
        flag = controls.get("automatic-chat-input")
        if isinstance(flag, bool):
            return flag
    for f in _CHAT_BY_TYPING_FIELDS:
        if f in data:
            return bool(data[f])
    return None


def _parse_chord(value) -> tuple[frozenset[str], str] | None:
    """Parse a TTR chord string ('enter', 'alt-enter', 'ctrl-x') into a
    (modifiers, keysym) pair.

    Split on '-': the last token is the key, preceding tokens are modifiers
    normalized to 'alt'/'ctrl'/'shift'. Named keys translate through
    _TTR_VALUE_TO_KEYSYM; printable single chars pass through verbatim per
    the keymap convention (see the table's comment). Returns None for
    missing/unparseable values so the caller can fall back to the stock
    chord."""
    if not isinstance(value, str) or not value:
        return None
    tokens = value.lower().split("-")
    mods = set()
    for tok in tokens[:-1]:
        norm = _CHORD_MOD_NORMALIZE.get(tok)
        if norm is None:
            return None
        mods.add(norm)
    key = tokens[-1]
    if key in _TTR_VALUE_TO_KEYSYM:
        keysym = _TTR_VALUE_TO_KEYSYM[key]
    elif len(key) == 1 and key.isprintable() and not key.isspace():
        keysym = key
    else:
        return None
    return (frozenset(mods), keysym)


def _resolve_chat_open_chords(controls: dict) -> tuple[tuple[frozenset[str], str], ...]:
    """Chat-open chords for a parsed controls dict: (chat, groupChat).

    Each slot independently falls back to its stock chord (enter /
    alt-enter) when the value is missing or unparseable."""
    chat = _parse_chord(controls.get("chat"))
    group = _parse_chord(controls.get("groupChat"))
    return (
        chat if chat is not None else _DEFAULT_CHAT_OPEN_CHORDS[0],
        group if group is not None else _DEFAULT_CHAT_OPEN_CHORDS[1],
    )


def resolve_chat_block_list(s: TtrSettings) -> set[str]:
    """Keysym strings to block for chat-off toons given a parsed TtrSettings.

    Always includes Return and Escape. Adds a-z when chat-by-typing is on,
    because in that TTR config any letter press opens chat."""
    block = {"Return", "Escape"}
    if s.chat_by_typing_enabled_resolved:
        block.update(string.ascii_lowercase)
    return block


_TTR_CONTROL_TO_ACTION = {
    "forward": "forward", "reverse": "reverse", "left": "left", "right": "right",
    "jump": "jump", "stickerBook": "book", "showGags": "gags",
    "showTasks": "tasks", "showMap": "map",
    "performAction": "action",
}

# TTR's settings.json control values normalized for TTMT's keymap storage.
# Named/special strings (arrows, modifiers, control cluster, nav keys, F-keys)
# are translated to their X11 keysym names here. Printable single-char values
# (a-z and others like '\\') intentionally fall through verbatim — the keymap
# must store the raw char so pynput event matching works at runtime.
# _resolve_keysym() in input_service.py handles the raw-char → keysym
# translation at send time.
#
# Confirmed by inspecting a real Windows TTR install's settings.json:
# C:\Program Files (x86)\Toontown Rewritten\settings.json
_TTR_VALUE_TO_KEYSYM = {
    # Modifiers
    "shift": "Shift_L", "control": "Control_L", "alt": "Alt_L",
    # Arrow keys (TTR uses the 'arrow_*' aliases for the default movement
    # bindings — bare 'up'/'down'/'left'/'right' are kept for back-compat
    # in case TTR ever changes the convention).
    "arrow_up":    "Up",    "up":    "Up",
    "arrow_down":  "Down",  "down":  "Down",
    "arrow_left":  "Left",  "left":  "Left",
    "arrow_right": "Right", "right": "Right",
    # Whitespace / control
    "space": "space", "escape": "Escape", "enter": "Return",
    "tab": "Tab", "backspace": "BackSpace", "delete": "Delete",
    # Intentionally no entry for "\\": pynput delivers the raw char '\\' and
    # the keymap must store it the same way. _resolve_keysym('\\') converts to
    # the X11 keysym 'backslash' at send time.
    # Navigation cluster
    "home": "Home", "end": "End",
    "page_up": "Prior", "page_down": "Next",
    "insert": "Insert",
    # Function keys F1–F12
    "f1":  "F1",  "f2":  "F2",  "f3":  "F3",  "f4":  "F4",
    "f5":  "F5",  "f6":  "F6",  "f7":  "F7",  "f8":  "F8",
    "f9":  "F9",  "f10": "F10", "f11": "F11", "f12": "F12",
}


def apply_ttr_controls_to_set(keymap_manager, set_index: int, controls: dict) -> int:
    """Apply parsed TTR controls onto the TTR keymap bucket's set at set_index.

    Returns the count of fields applied. Single-letter values pass through
    untouched; known TTR-specific names like 'control' are translated to the
    project's Xkeysym strings.
    """
    n = 0
    for ttr_key, action in _TTR_CONTROL_TO_ACTION.items():
        val = controls.get(ttr_key)
        if val is None:
            continue
        keymap_manager.update_set_key(
            "ttr", set_index, action, _TTR_VALUE_TO_KEYSYM.get(val, val)
        )
        n += 1
    return n
