"""Enumerate installed Steam Proton compatibility tools.

Scans every known Steam root for both:
  * Official Protons under <root>/steamapps/common/Proton *
  * User-installed tools under <root>/compatibilitytools.d/<name>/

Returns a deduped, sorted list of ProtonTool entries that the
CC launcher resolver and Settings picker consume.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Iterable


# Known mapping from official Proton dir basename to the internal alias
# Steam writes into CompatToolMapping. Steam tracks officials by these
# short slugs ("proton_9", "proton_experimental", etc.); the dir on
# disk has a different, human-readable name. Without this mapping, the
# resolver's step 2 (CompatToolMapping → ProtonTool.name) can never
# match for officials. Keep this list narrow — only well-known
# stable/beta/experimental/hotfix entries. Anything we miss falls
# through to the dir basename and step 2 simply doesn't match (the
# cascade then handles it via step 3 / step 4).
_OFFICIAL_NAME_ALIASES: dict[str, str] = {
    "Proton 9.0 (Beta)": "proton_9",
    "Proton 9.0": "proton_9",
    "Proton 8.0": "proton_8",
    "Proton 7.0": "proton_7",
    "Proton 6.3": "proton_63",
    "Proton 5.13": "proton_513",
    "Proton - Experimental": "proton_experimental",
    "Proton Experimental": "proton_experimental",
    "Proton - Hotfix": "proton_hotfix",
    "Proton Hotfix": "proton_hotfix",
}


@dataclass(frozen=True)
class ProtonTool:
    """A discovered Proton build.

    Attributes
    ----------
    name
        Internal name Steam uses to reference this tool (e.g. "proton_9",
        "proton-cachyos"). Must match the value Steam writes into
        CompatToolMapping[<appid>].name in config.vdf for cascade step 2
        to match.
    display_name
        Human-facing label for the picker (e.g. "Proton-CachyOS 9.0",
        "Proton 9.0 (Beta)").
    proton_dir
        Absolute path to the directory containing the `proton`
        executable.
    source
        "official" (steamapps/common) or "compatibilitytools.d".
    steam_root
        Which Steam root this came from.
    version_key
        Tuple of integers extracted from the name, used for sort order.
        Larger tuples sort newer.
    """

    name: str
    display_name: str
    proton_dir: str
    source: str
    steam_root: str
    version_key: tuple[int, ...]


_DEFAULT_STEAM_ROOTS = [
    "~/.local/share/Steam",
    "~/.steam/steam",
    "~/.var/app/com.valvesoftware.Steam/.local/share/Steam",
]


def _default_roots() -> list[str]:
    return [os.path.expanduser(p) for p in _DEFAULT_STEAM_ROOTS]


def _version_key_from_name(name: str) -> tuple[int, ...]:
    """Extract a sortable version tuple from a tool name.

    Examples:
        "Proton 9.0 (Beta)"            -> (9, 0)
        "GE-Proton9-26"                -> (9, 26)
        "Proton-CachyOS-9.0-20251214"  -> (9, 0, 20251214)
        "Proton - Experimental"        -> ()
    """
    nums = re.findall(r"\d+", name)
    return tuple(int(n) for n in nums)


def _parse_user_tool_vdf(path: str) -> tuple[str, str] | None:
    """Parse <dir>/compatibilitytool.vdf for (internal_name, display_name).

    Returns None on any error or unexpected shape.

    The file has the form:
      "compatibilitytools"
      {
        "compat_tools"
        {
          "<internal_name>"
          {
            "display_name" "<display>"
            ...
          }
        }
      }
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return None
    # Locate the compat_tools block.
    m = re.search(r'"compat_tools"\s*\{', text)
    if not m:
        return None
    rest = text[m.end():]
    # First quoted key after the opening brace is the internal name.
    key_match = re.search(r'"([^"]+)"\s*\{', rest)
    if not key_match:
        return None
    internal = key_match.group(1)
    body = rest[key_match.end():]
    # display_name inside that block; tolerate any-order keys.
    disp_match = re.search(r'"display_name"\s*"([^"]*)"', body)
    display = disp_match.group(1) if disp_match else internal
    return internal, display


def _read_proton_dir_entry(
    base: str, source: str, steam_root: str
) -> ProtonTool | None:
    """Build a ProtonTool from a candidate directory, or None if invalid."""
    proton_bin = os.path.join(base, "proton")
    if not os.path.isfile(proton_bin) or not os.access(proton_bin, os.X_OK):
        return None
    dir_name = os.path.basename(base.rstrip(os.sep))
    if source == "compatibilitytools.d":
        parsed = _parse_user_tool_vdf(
            os.path.join(base, "compatibilitytool.vdf")
        )
        if parsed:
            internal, display = parsed
        else:
            internal = dir_name
            display = dir_name
    else:
        # official
        internal = _OFFICIAL_NAME_ALIASES.get(dir_name, dir_name)
        display = dir_name
    return ProtonTool(
        name=internal,
        display_name=display,
        proton_dir=base,
        source=source,
        steam_root=steam_root,
        version_key=_version_key_from_name(dir_name),
    )


def enumerate_proton_tools(
    steam_roots: Iterable[str] | None = None,
) -> list[ProtonTool]:
    """Scan Steam roots for installed Proton builds.

    Returns
    -------
    list[ProtonTool]
        Deduped and sorted. Dedup keys on realpath of the `proton`
        binary — first-seen wins (root priority: native → .steam/steam
        → flatpak). Sort: user-installed before official; within each
        group, newest first by version_key, then mtime descending.

    Never raises. Roots that don't exist are skipped silently.
    """
    roots = list(steam_roots) if steam_roots is not None else _default_roots()
    found: list[ProtonTool] = []
    seen: set[str] = set()
    for root in roots:
        if not os.path.isdir(root):
            continue
        # User-installed tools.
        ctd = os.path.join(root, "compatibilitytools.d")
        if os.path.isdir(ctd):
            for entry in sorted(os.listdir(ctd)):
                base = os.path.join(ctd, entry)
                if not os.path.isdir(base):
                    continue
                tool = _read_proton_dir_entry(base, "compatibilitytools.d", root)
                if tool is None:
                    continue
                real = os.path.realpath(os.path.join(tool.proton_dir, "proton"))
                if real in seen:
                    continue
                seen.add(real)
                found.append(tool)
        # Official Protons.
        common = os.path.join(root, "steamapps", "common")
        if os.path.isdir(common):
            for entry in sorted(os.listdir(common)):
                if not entry.startswith("Proton"):
                    continue
                base = os.path.join(common, entry)
                if not os.path.isdir(base):
                    continue
                tool = _read_proton_dir_entry(base, "official", root)
                if tool is None:
                    continue
                real = os.path.realpath(os.path.join(tool.proton_dir, "proton"))
                if real in seen:
                    continue
                seen.add(real)
                found.append(tool)

    def _mtime(p: ProtonTool) -> float:
        try:
            return os.path.getmtime(os.path.join(p.proton_dir, "proton"))
        except OSError:
            return 0.0

    def _sort_key(p: ProtonTool) -> tuple:
        group_rank = 0 if p.source == "compatibilitytools.d" else 1
        # Tools with no parseable version (e.g. "Proton - Experimental")
        # have an empty version_key. Push them to the bottom of their
        # group via has_version=1 so they tiebreak on mtime alone, not
        # the (incorrect) "empty tuple sorts first" Python default.
        has_version = 0 if p.version_key else 1
        # Pad to a fixed length so longer tuples (more specific, e.g.
        # date-suffixed builds like Proton-CachyOS-9.0-20251214) sort
        # BEFORE shorter ones with the same prefix. Without padding,
        # tuple lex-compare puts shorter tuples first, which is
        # backwards from "newest first."
        padded = (p.version_key + (0,) * 6)[:6]
        neg_version = tuple(-n for n in padded)
        return (group_rank, has_version, neg_version, -_mtime(p))

    found.sort(key=_sort_key)
    return found
