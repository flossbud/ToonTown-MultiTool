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


def make_object_key(file_path: str, platform_str: str, server_name: str) -> str:
    """Download-server object key for a manifest file, replicating CC's own
    launcher (launcher.util.downloads.make_object_key). For a Cloudflare/R2
    server the key is a path: '<platform>/<filePath-as-posix>.gz' (CC's current
    scheme). For any other (legacy) server it is sha1(filePath + platform).
    filePath is normalized to forward slashes (CC computes Path(...).as_posix()
    under Windows, where the manifest's backslashes are separators)."""
    posix = file_path.replace("\\", "/")
    if "cloudflare" in server_name.lower().strip():
        return f"{platform_str}/{posix}.gz"
    return hashlib.sha1((file_path + platform_str).encode("utf-8"),
                        usedforsecurity=False).hexdigest()


def fetch_verified(entry: dict, base_url: str, server_name: str) -> bytes:
    """Download the entry's gzip blob from the download server, decompress, and
    verify the decompressed bytes against the manifest 'sha1'. Return the
    verified bytes. Raise ValueError on a malformed entry or hash mismatch.

    Note: the manifest's 'compressed_sha1' is NOT checked — the gzip blobs CC
    serves carry an mtime/filename header, so the compressed bytes' hash is not
    stable across re-gzips. The decompressed content hash ('sha1') is the
    authoritative integrity gate."""
    if not entry.get("sha1"):
        raise ValueError("manifest entry missing sha1")
    key = make_object_key(entry["filePath"], entry["_platform"], server_name)
    url = base_url.rstrip("/") + "/" + key
    r = requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=_HTTP_TIMEOUT)
    r.raise_for_status()
    data = gzip.decompress(r.content)
    got = hashlib.sha1(data, usedforsecurity=False).hexdigest()
    if got != entry["sha1"]:
        raise ValueError(f"file-hash mismatch for {entry['filePath']}: {got}")
    return data


def resolve_download_server(launcher_token: str, realm: str) -> tuple:
    """GET /metadata with the launcher token; return (base_url, server_name)
    for the realm's download server. CC nests downloadservers INSIDE the
    matching realm (not at the top level), so prefer the realm whose slug
    matches, then any realm, then a top-level list as a defensive fallback. The
    server name selects the object-key scheme (see make_object_key). Raise
    ValueError if none. Network errors propagate as requests.RequestException."""
    headers = dict(CC_HEADERS)
    headers["Authorization"] = f"Bearer {launcher_token}"
    r = requests.get(CC_METADATA_URL, headers=headers, timeout=_HTTP_TIMEOUT)
    r.raise_for_status()
    data = r.json()
    realms = data.get("realms") or []
    servers = []
    for rlm in realms:
        if rlm.get("slug") == realm:
            servers = rlm.get("downloadservers") or []
            break
    if not servers:
        for rlm in realms:
            servers += rlm.get("downloadservers") or []
    servers += data.get("downloadservers") or []
    for s in servers:
        if s.get("base_url"):
            return s["base_url"], (s.get("name") or "")
    raise ValueError("no download server with base_url in /metadata")


def _local_path(game_dir: str, raw_file_path: str) -> str:
    """Host path of a manifest file: join game_dir with the filePath. Manifest
    paths use backslashes (windows binaries) or forward slashes (resources), so
    normalize both to the OS separator."""
    parts = [p for p in raw_file_path.replace("\\", "/").split("/") if p]
    return os.path.join(game_dir, *parts)


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


# game_dir (realpath) -> SHA256 of the manifest last verified clean this
# session. Lets multiple account launches share one verification pass while
# still re-verifying if CC pushes an update mid-session.
_verified_manifests = {}

# Serializes verify+patch across concurrent account launches so they don't
# redundantly re-download and collide on shared staging/temp paths.
_patch_lock = threading.Lock()


def reset_verify_cache() -> None:
    _verified_manifests.clear()


def _manifest_sha(files: list) -> str:
    key = sorted((f["filePath"], f.get("sha1", "")) for f in files)
    return hashlib.sha256(json.dumps(key).encode()).hexdigest()


class CCPatcher(QObject):
    progress = Signal(str, int)   # (human message, percent 0-100)
    up_to_date = Signal()         # nothing to do (or offline -> proceed)
    patched = Signal(list)        # [filePaths] successfully updated
    failed = Signal(str)          # fatal error; do not launch

    def verify_and_patch(self, game_dir: str, launcher_token: str,
                         realm: str = "production") -> None:
        """Verify the selected CC install against CC's manifest and repair
        stale files on a background thread. Emits exactly one terminal signal
        (up_to_date | patched | failed)."""
        game_dir = os.path.realpath(game_dir)
        platform = _platform_for_os()

        def _run():
            self.progress.emit("Checking Corporate Clash files…", 0)
            with _patch_lock:
                try:
                    try:
                        files = fetch_all_manifests(realm, platform)
                    except requests.RequestException as e:
                        print(f"[CCPatcher] manifest unreachable, proceeding: {e}")
                        self.up_to_date.emit()
                        return
                    msha = _manifest_sha(files)
                    if _verified_manifests.get(game_dir) == msha:
                        self.up_to_date.emit()
                        return
                    stale = select_stale(files, game_dir)
                    if not stale:
                        _verified_manifests[game_dir] = msha
                        self.up_to_date.emit()
                        return
                    base, server_name = resolve_download_server(launcher_token, realm)
                    updated = []
                    total = len(stale)
                    for i, entry in enumerate(stale):
                        self.progress.emit(f"Updating {entry['filePath']}…",
                                           int(i / total * 100))
                        data = fetch_verified(entry, base, server_name)
                        dest = _local_path(game_dir, entry["filePath"])
                        ensure_parent_dir(dest)
                        place_file(data, dest)
                        updated.append(entry["filePath"])
                    _verified_manifests[game_dir] = msha
                    self.progress.emit("Corporate Clash files updated.", 100)
                    self.patched.emit(updated)
                except Exception as e:
                    self.failed.emit(f"Corporate Clash file update failed: {e}")

        threading.Thread(target=_run, daemon=True).start()
