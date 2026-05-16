"""Parse Steam's config.vdf for CompatToolMapping entries.

We only care about three keys inside
InstallConfigStore.Software.Valve.Steam.CompatToolMapping:
  * "<appid>".name    — per-game compat tool override
  * "0".name          — global Steam Play default
This is a deliberately narrow parser. config.vdf is text-VDF (key/string
pairs in nested braces). We do not implement a general-purpose VDF
library — just enough to walk to CompatToolMapping and read string
values out.

Never raises. All parse failures yield None and log once.
"""

from __future__ import annotations

import os
import re


_NESTED_PATH = (
    "InstallConfigStore",
    "Software",
    "Valve",
    "Steam",
    "CompatToolMapping",
)


def _config_path(steam_root: str) -> str:
    return os.path.join(steam_root, "config", "config.vdf")


def _read_file(path: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def _find_block(text: str, key: str, start: int) -> tuple[int, int] | None:
    """Find "<key>" { ... } at depth-1 nesting starting at `start`.

    Returns (open_brace_index, close_brace_index) or None.
    Open brace is the `{` after the key; close brace is its match.
    """
    pattern = re.compile(r'"' + re.escape(key) + r'"\s*\{')
    m = pattern.search(text, start)
    if not m:
        return None
    open_idx = m.end() - 1
    depth = 0
    i = open_idx
    while i < len(text):
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return open_idx, i
        elif c == '"':
            # Skip a quoted string (may contain { or }).
            j = i + 1
            while j < len(text) and text[j] != '"':
                if text[j] == "\\" and j + 1 < len(text):
                    j += 2
                    continue
                j += 1
            i = j
        i += 1
    return None


def _walk_to_mapping(text: str) -> tuple[int, int] | None:
    """Walk the nested path to the CompatToolMapping block."""
    start = 0
    end = len(text)
    for key in _NESTED_PATH:
        block = _find_block(text[:end], key, start)
        if block is None:
            return None
        open_idx, close_idx = block
        # Search inside this block for the next key.
        start = open_idx + 1
        end = close_idx
    return start, end


def _extract_name(block: str, appid: str) -> str | None:
    """Find "<appid>" { ... "name" "<value>" ... } within block."""
    sub = _find_block(block, appid, 0)
    if sub is None:
        return None
    body = block[sub[0] + 1 : sub[1]]
    m = re.search(r'"name"\s*"([^"]*)"', body)
    if m is None:
        return None
    val = m.group(1)
    return val or None


def steam_compat_choice(steam_root: str, appid: str) -> str | None:
    """Return Steam's compat tool choice for this appid.

    Cascade inside this function:
      1. CompatToolMapping[appid].name if non-empty → return it
      2. CompatToolMapping["0"].name if non-empty → return it
      3. None
    """
    path = _config_path(steam_root)
    text = _read_file(path)
    if text is None:
        return None
    try:
        block = _walk_to_mapping(text)
        if block is None:
            return None
        open_idx, close_idx = block
        body = text[open_idx + 1 : close_idx]
        return _extract_name(body, appid) or _extract_name(body, "0")
    except Exception as e:  # pragma: no cover — defensive
        print(f"[CCLauncher] steam_compat_choice failed to parse "
              f"{path}: {type(e).__name__}: {e}")
        return None
