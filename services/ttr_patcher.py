"""TTR game-file patcher.

Keeps a TTR install in sync with TTR's official patch manifest before launch,
so a stale/modified game file never aborts the engine's integrity check.
TTMT launches TTREngine directly (login API + cookie) and otherwise has no
patch step; this module fills that gap the way the official launcher does.
"""

from __future__ import annotations

import bz2
import hashlib
import json
import os
import sys
import tempfile
import threading
import urllib.parse

import requests
from PySide6.QtCore import QObject, Signal

from utils.host_spawn import host_run, host_visible_cache_dir, in_flatpak

MANIFEST_URL = "https://cdn.toontownrewritten.com/content/patchmanifest.txt"
_MIRROR_ENDPOINTS = (
    "https://www.toontownrewritten.com/api/mirrors",
    "https://cdn.toontownrewritten.com/mirrors.txt",
)
_FALLBACK_MIRROR = "https://download.toontownrewritten.com/patches/"
_HTTP_TIMEOUT = 30
_USER_AGENT = "ToontownMultiTool"


def _platform_tokens() -> set:
    """Manifest 'only' tokens that mark a file as applicable to this OS."""
    if sys.platform == "win32":
        return {"win32", "win64"}
    if sys.platform == "darwin":
        return {"darwin"}
    return {"linux"}


def _applicable(entry: dict) -> bool:
    only = entry.get("only")
    if only is None:
        return True
    return bool(set(only) & _platform_tokens())


def fetch_manifest() -> dict:
    """GET the patch manifest. Raises requests.RequestException on network error."""
    r = requests.get(MANIFEST_URL, headers={"User-Agent": _USER_AGENT}, timeout=_HTTP_TIMEOUT)
    r.raise_for_status()
    return r.json()


def local_sha1(path: str) -> str | None:
    """Streamed SHA1 of a local file, or None if it doesn't exist."""
    if not os.path.isfile(path):
        return None
    h = hashlib.sha1(usedforsecurity=False)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def select_stale(manifest: dict, engine_dir: str) -> list[tuple[str, dict]]:
    """Return [(filename, entry)] for applicable files whose on-disk SHA1
    doesn't match the manifest 'hash' (mismatched or missing)."""
    stale = []
    for filename, entry in manifest.items():
        if not _applicable(entry):
            continue
        expected = entry.get("hash")
        if not expected:
            continue
        if local_sha1(os.path.join(engine_dir, filename)) != expected:
            stale.append((filename, entry))
    return stale
