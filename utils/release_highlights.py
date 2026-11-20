"""Structured release notes: three highlights and a list of fixes.

The update sheet and the What's new sheet show three highlights (a title of
one to three words and one sentence) and a count of fixes, not the raw
release markdown. The structure is authored once per release, in
``assets/whats_new.json``:

    {
      "version": "v0.8.0-alpha.2",
      "highlights": [{"title": "Light theme", "text": "One sentence."}, ...],
      "fixes": ["One line per fix.", ...]
    }

and travels two ways:

* shipped in the build, where What's new reads it on the first launch of
  that version (``shipped``);
* in the GitHub release body, as a comment block the update offer reads from
  the release feed (``from_release_body``), written by ``body_block``:

      <!-- ttmt:highlights
      {"highlights": [...], "fixes": 3}
      -->

A release without the block still updates: the offer just has no highlight
list.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Optional

MAX_HIGHLIGHTS = 3
_BLOCK_RE = re.compile(r"<!--\s*ttmt:highlights\s*(\{.*?\})\s*-->", re.DOTALL)


@dataclass(frozen=True)
class Highlight:
    title: str
    text: str = ""


@dataclass(frozen=True)
class ReleaseNotes:
    version: str = ""
    highlights: tuple = field(default_factory=tuple)
    fix_count: int = 0

    def __bool__(self) -> bool:
        return bool(self.highlights)

    def more_text(self) -> str:
        """"+ 3 bug fixes", or "" when there are none."""
        if self.fix_count <= 0:
            return ""
        return f"+ {self.fix_count} bug fix" + ("" if self.fix_count == 1 else "es")


def _parse(data, version: str = "") -> Optional[ReleaseNotes]:
    if not isinstance(data, dict):
        return None
    highlights = []
    for entry in data.get("highlights") or []:
        if isinstance(entry, dict) and str(entry.get("title") or "").strip():
            highlights.append(Highlight(str(entry["title"]).strip(),
                                        str(entry.get("text") or "").strip()))
    fixes = data.get("fixes")
    if isinstance(fixes, list):
        fix_count = len(fixes)
    elif isinstance(fixes, int) and not isinstance(fixes, bool):
        fix_count = max(0, fixes)
    else:
        fix_count = 0
    if not highlights:
        return None
    return ReleaseNotes(version=str(data.get("version") or version),
                        highlights=tuple(highlights[:MAX_HIGHLIGHTS]),
                        fix_count=fix_count)


def from_release_body(body: str, version: str = "") -> Optional[ReleaseNotes]:
    """The highlights block of a GitHub release body, or None."""
    match = _BLOCK_RE.search(body or "")
    if match is None:
        return None
    try:
        return _parse(json.loads(match.group(1)), version)
    except (ValueError, TypeError):
        return None


def from_file(path: str) -> Optional[ReleaseNotes]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return _parse(json.load(fh))
    except (OSError, ValueError, TypeError):
        return None


def shipped() -> Optional[ReleaseNotes]:
    """The notes this build carries."""
    from utils.asset_paths import asset_path
    return from_file(asset_path("whats_new.json"))


def body_block(path: str) -> str:
    """The comment block to append to a release body, built from the shipped
    file ("" if the file is missing or empty). Fixes travel as a count."""
    notes = from_file(path)
    if notes is None:
        return ""
    payload = {
        "highlights": [{"title": h.title, "text": h.text} for h in notes.highlights],
        "fixes": notes.fix_count,
    }
    return "<!-- ttmt:highlights\n" + json.dumps(payload, ensure_ascii=False) + "\n-->"


if __name__ == "__main__":
    # python -m utils.release_highlights [path]: print the block for a release body.
    import os
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "assets", "whats_new.json")
    print(body_block(target))
