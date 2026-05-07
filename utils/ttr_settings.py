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

# Field names TTR may expose for the chat-by-typing toggle. First present field
# wins. Tightened during B.3 once a real-world settings.json is probed.
_CHAT_BY_TYPING_FIELDS: tuple[str, ...] = (
    "chat-by-typing", "chatByTyping", "enableChatByTyping", "typingChat",
)

_FLATPAK_PATH = os.path.expanduser(
    "~/.var/app/com.toontownrewritten.Launcher/data/settings.json"
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
    )


def _has_letter_hotkeys(controls: dict) -> bool:
    for v in controls.values():
        if isinstance(v, str) and len(v) == 1 and v.lower() in string.ascii_lowercase:
            return True
    return False


def _explicit_chat_flag(data: dict) -> bool | None:
    for f in _CHAT_BY_TYPING_FIELDS:
        if f in data:
            return bool(data[f])
    return None


def resolve_chat_block_list(s: TtrSettings) -> set[str]:
    """Keysym strings to block for chat-off toons given a parsed TtrSettings.

    Always includes Return and Escape. Adds a-z when chat-by-typing is on,
    because in that TTR config any letter press opens chat."""
    block = {"Return", "Escape"}
    if s.chat_by_typing_enabled_resolved:
        block.update(string.ascii_lowercase)
    return block


_TTR_CONTROL_TO_DIRECTION = {
    "forward": "up", "reverse": "down", "left": "left", "right": "right",
    "jump": "jump", "stickerBook": "book", "showGags": "gags",
    "showTasks": "tasks", "showMap": "map",
}

# TTR's settings.json control values, translated to TTMT's X-keysym strings.
# Keys are the actual literal strings TTR writes; values are what the rest
# of TTMT (KeymapManager, InputService, Win32Backend, XlibBackend) expects.
#
# Confirmed by inspecting a real Windows TTR install's settings.json:
# C:\Program Files (x86)\Toontown Rewritten\settings.json
#
# Anything not in this table falls through verbatim. That's intentional for
# letter hotkeys (a-z) — TTR writes them as "w" / "a" etc., which our
# keymap stores literally.
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
    """Apply parsed TTR controls onto the given keymap set.

    Returns the count of fields applied. Single-letter values pass through
    untouched (TTR uses a-z verbatim for letter hotkeys); known TTR-specific
    names like 'control' are translated to the project's Xkeysym strings."""
    n = 0
    for ttr_key, direction in _TTR_CONTROL_TO_DIRECTION.items():
        val = controls.get(ttr_key)
        if val is None:
            continue
        keymap_manager.update_set_key(set_index, direction, _TTR_VALUE_TO_KEYSYM.get(val, val))
        n += 1
    return n
