"""Corporate Clash game-file patcher.

Keeps a CC install in sync with CC's official public manifest before launch,
mirroring services/ttr_patcher.py. CC's manifest is JSON
({"files":[{fileName,filePath,sha1,compressed_sha1}]}), compressed with gzip,
and the download name is sha1(filePath + platformToken). Discovery of the
download base comes from the /metadata response TTMT already fetches.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import subprocess
import sys
import threading

import requests
from PySide6.QtCore import QObject, Signal

from services.cc_login_service import CC_METADATA_URL, CC_HEADERS
from services.ttr_patcher import place_file, local_sha1
from utils.host_spawn import host_run, in_flatpak

_MANIFEST_URL = "https://corporateclash.net/api/v1/launcher/manifest/v3/{realm}/{platform}"
_HTTP_TIMEOUT = 30
_USER_AGENT = "ToontownMultiTool"

# Download-name hash tokens. Platform binaries use the platform name; shared
# assets use "resources".
_DOWNLOAD_TOKENS = {"windows": "windows", "macos": "macos", "resources": "resources"}


def _platform_for_os(plat: str | None = None) -> str:
    """The manifest platform to fetch alongside 'resources'. Every Linux wine
    runtime runs the Windows build, so Linux -> 'windows'."""
    plat = plat or sys.platform
    return "macos" if plat == "darwin" else "windows"


def fetch_manifest(realm: str, platform: str) -> list:
    """GET one platform manifest; return its files list, each tagged with
    _platform. Raises requests.RequestException on network error."""
    url = _MANIFEST_URL.format(realm=realm, platform=platform)
    r = requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=_HTTP_TIMEOUT)
    r.raise_for_status()
    files = r.json().get("files", []) or []
    for f in files:
        f["_platform"] = platform
    return files


def fetch_all_manifests(realm: str, platform: str) -> list:
    """Fetch the OS platform manifest plus the shared 'resources' manifest."""
    return fetch_manifest(realm, platform) + fetch_manifest(realm, "resources")
