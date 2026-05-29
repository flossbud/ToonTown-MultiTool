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


def download_name(raw_file_path: str, platform_token: str) -> str:
    """CC's download filename: sha1 of the RAW manifest filePath (backslashes
    intact) concatenated with the platform token."""
    token = _DOWNLOAD_TOKENS.get(platform_token, platform_token)
    return hashlib.sha1((raw_file_path + token).encode("utf-8"),
                        usedforsecurity=False).hexdigest()


def fetch_verified(entry: dict, base_url: str) -> bytes:
    """Download the entry's gzip blob, verify compressed_sha1, decompress,
    verify sha1. Return verified bytes. Raise ValueError on any mismatch."""
    if not entry.get("sha1") or not entry.get("compressed_sha1"):
        raise ValueError("manifest entry missing sha1/compressed_sha1")
    name = download_name(entry["filePath"], entry["_platform"])
    url = base_url.rstrip("/") + "/" + name
    r = requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=_HTTP_TIMEOUT)
    r.raise_for_status()
    comp = r.content
    got_comp = hashlib.sha1(comp, usedforsecurity=False).hexdigest()
    if got_comp != entry["compressed_sha1"]:
        raise ValueError(f"compressed-hash mismatch for {entry['filePath']}: {got_comp}")
    data = gzip.decompress(comp)
    got = hashlib.sha1(data, usedforsecurity=False).hexdigest()
    if got != entry["sha1"]:
        raise ValueError(f"file-hash mismatch for {entry['filePath']}: {got}")
    return data


def resolve_download_base(launcher_token: str, realm: str) -> str:
    """GET /metadata with the launcher token; return the first download
    server's base_url (preferring one matching realm). Raise ValueError if
    none. Network errors propagate as requests.RequestException."""
    headers = dict(CC_HEADERS)
    headers["Authorization"] = f"Bearer {launcher_token}"
    r = requests.get(CC_METADATA_URL, headers=headers, timeout=_HTTP_TIMEOUT, verify=True)
    r.raise_for_status()
    servers = r.json().get("downloadservers") or []
    for s in servers:
        if s.get("base_url") and s.get("realm") == realm:
            return s["base_url"]
    for s in servers:
        if s.get("base_url"):
            return s["base_url"]
    raise ValueError("no download server with base_url in /metadata")


def _local_path(game_dir: str, raw_file_path: str) -> str:
    """Host path of a manifest file: join game_dir with the filePath, its
    backslashes converted to the OS separator."""
    return os.path.join(game_dir, *raw_file_path.split("\\"))


def _host_sha1_batch(paths: list) -> dict:
    """SHA1 every path host-side in one batched `sha1sum` call (flatpak path).
    A path sha1sum cannot read (missing) is simply absent from the result.
    Output line format is '<hash>  <path>' (hash, two spaces, path)."""
    if not paths:
        return {}
    res = host_run(["sha1sum", "--", *paths], capture_output=True, text=True)
    out = {}
    for line in (res.stdout or "").splitlines():
        h, sep, path = line.partition("  ")
        if sep and path:
            out[path] = h
    return out


def select_stale(files: list, game_dir: str) -> list:
    """Return the manifest entries whose on-disk SHA1 != manifest sha1
    (mismatched or missing). Under flatpak, hash host-side in one batch so
    prefixes under another flatpak's ~/.var/app are reachable."""
    paths = [_local_path(game_dir, f["filePath"]) for f in files]
    if in_flatpak():
        hashed = _host_sha1_batch(paths)
        return [f for f, path in zip(files, paths) if hashed.get(path) != f["sha1"]]
    return [f for f, path in zip(files, paths) if local_sha1(path) != f["sha1"]]


def ensure_parent_dir(dest_path: str) -> None:
    """Create the parent dir of dest_path (host-side under flatpak)."""
    parent = os.path.dirname(dest_path)
    if not parent:
        return
    if in_flatpak():
        host_run(["mkdir", "-p", "--", parent], check=True)
    else:
        os.makedirs(parent, exist_ok=True)
