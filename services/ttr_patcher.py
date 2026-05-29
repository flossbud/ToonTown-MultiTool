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


def resolve_mirror() -> str:
    """Return the download base URL. Tries TTR's mirror endpoints in order,
    falling back to the canonical patches host."""
    for url in _MIRROR_ENDPOINTS:
        try:
            r = requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=_HTTP_TIMEOUT)
            r.raise_for_status()
            mirrors = r.json()
            if mirrors:
                return mirrors[0]
        except (requests.RequestException, ValueError):
            continue
    return _FALLBACK_MIRROR


def fetch_verified(entry: dict, mirror: str) -> bytes:
    """Download the entry's bz2 from the mirror, verify compHash, decompress,
    verify hash. Return the verified uncompressed bytes. Raise ValueError on a
    malformed entry or any hash mismatch (never returns unverified data)."""
    dl = entry.get("dl")
    if not dl or not entry.get("hash") or not entry.get("compHash"):
        raise ValueError("manifest entry missing dl/hash/compHash")
    base = mirror.rstrip("/") + "/"
    url = urllib.parse.urljoin(base, dl)
    r = requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=_HTTP_TIMEOUT)
    r.raise_for_status()
    comp = r.content
    got_comp = hashlib.sha1(comp, usedforsecurity=False).hexdigest()
    if got_comp != entry["compHash"]:
        raise ValueError(f"compressed-hash mismatch for {dl}: {got_comp}")
    data = bz2.decompress(comp)
    got = hashlib.sha1(data, usedforsecurity=False).hexdigest()
    if got != entry["hash"]:
        raise ValueError(f"file-hash mismatch for {dl}: {got}")
    return data


# engine_dir (realpath) -> SHA256 of the manifest last verified clean this
# session. Lets multiple account launches share one verification pass while
# still re-verifying if TTR pushes an update mid-session (manifest changes).
_verified_manifests = {}


def reset_verify_cache() -> None:
    _verified_manifests.clear()


def _manifest_sha(manifest: dict) -> str:
    return hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()


class TTRPatcher(QObject):
    progress = Signal(str, int)   # (human message, percent 0-100)
    up_to_date = Signal()         # nothing to do (or offline -> proceed)
    patched = Signal(list)        # [filenames] successfully updated
    failed = Signal(str)          # fatal error; do not launch

    def verify_and_patch(self, engine_dir: str) -> None:
        """Verify the install against the manifest and repair stale files on a
        background thread. Emits exactly one terminal signal
        (up_to_date | patched | failed)."""
        engine_dir = os.path.realpath(engine_dir)

        def _run():
            try:
                self.progress.emit("Checking TTR game files…", 0)
                try:
                    manifest = fetch_manifest()
                except requests.RequestException as e:
                    # Offline / manifest unreachable: don't block the launch.
                    print(f"[TTRPatcher] manifest unreachable, proceeding: {e}")
                    self.up_to_date.emit()
                    return
                msha = _manifest_sha(manifest)
                if _verified_manifests.get(engine_dir) == msha:
                    self.up_to_date.emit()
                    return
                stale = select_stale(manifest, engine_dir)
                if not stale:
                    _verified_manifests[engine_dir] = msha
                    self.up_to_date.emit()
                    return
                mirror = resolve_mirror()
                updated = []
                total = len(stale)
                for i, (filename, entry) in enumerate(stale):
                    self.progress.emit(f"Updating {filename}…", int(i / total * 100))
                    data = fetch_verified(entry, mirror)
                    place_file(data, os.path.join(engine_dir, filename))
                    updated.append(filename)
                _verified_manifests[engine_dir] = msha
                self.progress.emit("TTR game files updated.", 100)
                self.patched.emit(updated)
            except Exception as e:
                self.failed.emit(f"TTR game file update failed: {e}")

        threading.Thread(target=_run, daemon=True).start()


def place_file(data: bytes, dest_path: str) -> None:
    """Atomically install verified bytes at dest_path.

    In Flatpak the destination dir is mounted read-only in-sandbox, so the
    write crosses to the host via flatpak-spawn: stage the bytes in TTMT's
    host-visible cache, then host-side `cp` to a same-dir temp and `mv` it
    onto the destination (atomic rename). Outside Flatpak, write a same-dir
    temp and os.replace() it. The engine is not running during patching, so
    there is no read/write race.
    """
    name = os.path.basename(dest_path)
    if in_flatpak():
        staged = os.path.join(host_visible_cache_dir("ttr-patch"), name)
        with open(staged, "wb") as f:
            f.write(data)
        tmp = dest_path + ".ttmt.tmp"
        try:
            host_run(["cp", "--", staged, tmp], check=True)
            host_run(["mv", "-f", "--", tmp, dest_path], check=True)
        except BaseException:
            # mv may have failed after cp created the temp in the game dir;
            # remove the orphan (best-effort, host-side) so it can't accumulate
            # or be mistaken for a real file. check=False so cleanup never masks
            # the original error.
            try:
                host_run(["rm", "-f", "--", tmp], check=False)
            except Exception:
                pass
            raise
        finally:
            try:
                os.unlink(staged)
            except OSError:
                pass
    else:
        dest_dir = os.path.dirname(dest_path)
        fd, tmp = tempfile.mkstemp(dir=dest_dir, prefix="." + name + ".", suffix=".ttmt.tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, dest_path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
