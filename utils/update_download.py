"""Download a release asset in the background, with progress and resume.

The file is written to ``<name>.part`` beside its final path and renamed only
once it is complete and checked, so a path without ``.part`` is always a
whole, verified file. A dropped connection keeps the partial file; the next
``start`` asks the server for the rest with an HTTP Range request and picks
up at the byte it stopped at.

Checks, in order: the byte count against the release asset's ``size``, then
the SHA-256 when the release feed carries a ``digest`` for the asset.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
import time
from typing import Optional

from PySide6.QtCore import QObject, QThread, Signal

CHUNK = 64 * 1024
PROGRESS_INTERVAL_S = 0.1
CONNECT_TIMEOUT_S = 15
READ_TIMEOUT_S = 60

# Why a download stopped.
REASON_NETWORK = "network"        # worth resuming
REASON_VERIFY = "verify"          # the bytes were wrong; the partial file is gone
REASON_DISK = "disk"              # could not write
REASON_CANCELLED = "cancelled"


def download_dir() -> str:
    """Where update downloads live: one folder under the temp directory, so a
    partial file survives a restart of the app."""
    path = os.path.join(tempfile.gettempdir(), "ttmt-update")
    os.makedirs(path, exist_ok=True)
    return path


def asset_paths(asset: dict, out_dir: Optional[str] = None) -> tuple[str, str]:
    """(final path, partial path) for a release asset."""
    name = os.path.basename(asset.get("name") or "") or "download"
    final = os.path.join(out_dir or download_dir(), name)
    return final, final + ".part"


def expected_sha256(asset: dict) -> str:
    digest = str(asset.get("digest") or "")
    return digest.split(":", 1)[1].lower() if digest.startswith("sha256:") else ""


def partial_size(asset: dict, out_dir: Optional[str] = None) -> int:
    """Bytes already on disk for this asset (0 if none)."""
    final, partial = asset_paths(asset, out_dir)
    for path in (final, partial):
        try:
            return os.path.getsize(path)
        except OSError:
            continue
    return 0


def file_matches(path: str, asset: dict) -> bool:
    """True if ``path`` is the whole asset: right size, and right SHA-256
    when the feed gives one."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return False
    expected = int(asset.get("size") or 0)
    if expected > 0 and size != expected:
        return False
    want = expected_sha256(asset)
    if want:
        sha = hashlib.sha256()
        try:
            with open(path, "rb") as fh:
                for block in iter(lambda: fh.read(1024 * 1024), b""):
                    sha.update(block)
        except OSError:
            return False
        return sha.hexdigest() == want
    return size > 0


def _total_from_content_range(value: str) -> int:
    # "bytes 100-999/1000"
    try:
        return int(value.rsplit("/", 1)[1])
    except (IndexError, ValueError):
        return 0


def fetch(asset: dict, *, out_dir: Optional[str] = None, on_progress=None,
          cancelled=lambda: False, session=None) -> tuple[Optional[str], str]:
    """Download ``asset`` to its final path, resuming a partial file.

    Returns (path, "") on success or (None, reason). Blocking: run it on a
    worker thread. ``on_progress(received, total)`` is called at most about
    ten times a second; ``cancelled()`` is polled between chunks.
    """
    import requests

    url = asset.get("browser_download_url")
    if not url:
        return None, REASON_NETWORK
    final, partial = asset_paths(asset, out_dir)
    expected = int(asset.get("size") or 0)
    if file_matches(final, asset):
        if on_progress:
            size = os.path.getsize(final)
            on_progress(size, size)
        return final, ""

    try:
        have = os.path.getsize(partial)
    except OSError:
        have = 0
    if expected > 0 and have > expected:
        have = 0                          # not this asset's partial file
    http = session or requests
    headers = {"Range": f"bytes={have}-"} if have > 0 else {}
    try:
        with http.get(url, stream=True, headers=headers,
                      timeout=(CONNECT_TIMEOUT_S, READ_TIMEOUT_S)) as response:
            if response.status_code == 416 and have > 0:
                # Nothing left to send: the partial file is already whole.
                return _finish(final, partial, asset)
            response.raise_for_status()
            if response.status_code == 206:
                total = _total_from_content_range(
                    response.headers.get("Content-Range", "")) or expected
                mode = "ab"
            else:
                # The server ignored the range: start again from the top.
                total = int(response.headers.get("Content-Length") or 0) or expected
                have = 0
                mode = "wb"
            received = have
            last = 0.0
            # requests' own errors are OSErrors too: only opening and writing
            # the file count as a disk failure, the stream is caught below.
            try:
                fh = open(partial, mode)
            except OSError:
                return None, REASON_DISK
            with fh:
                for chunk in response.iter_content(chunk_size=CHUNK):
                    if cancelled():
                        return None, REASON_CANCELLED
                    if not chunk:
                        continue
                    try:
                        fh.write(chunk)
                    except OSError:
                        return None, REASON_DISK
                    received += len(chunk)
                    now = time.monotonic()
                    if on_progress and now - last >= PROGRESS_INTERVAL_S:
                        last = now
                        on_progress(received, total)
    except requests.RequestException:
        return None, REASON_NETWORK
    if on_progress:
        on_progress(received, total or received)
    if expected > 0 and received < expected:
        return None, REASON_NETWORK       # the stream ended early: resumable
    return _finish(final, partial, asset)


def _finish(final: str, partial: str, asset: dict) -> tuple[Optional[str], str]:
    if not file_matches(partial, asset):
        try:
            os.unlink(partial)
        except OSError:
            pass
        return None, REASON_VERIFY
    try:
        os.replace(partial, final)
    except OSError:
        return None, REASON_DISK
    return final, ""


def discard(asset: dict, out_dir: Optional[str] = None) -> None:
    """Remove this asset's downloaded and partial files."""
    for path in asset_paths(asset, out_dir):
        try:
            os.unlink(path)
        except OSError:
            pass


class _Worker(QObject):
    progress = Signal(int, int)
    done = Signal(str, str)          # path ("" on failure), reason

    def __init__(self, asset: dict, out_dir: Optional[str]):
        super().__init__()
        self._asset = asset
        self._out_dir = out_dir
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            path, reason = fetch(
                self._asset, out_dir=self._out_dir,
                on_progress=lambda received, total: self.progress.emit(received, total),
                cancelled=lambda: self._cancel)
        except Exception as error:  # noqa: BLE001
            path, reason = None, f"{REASON_NETWORK}: {error}"
        self.done.emit(path or "", reason)


class UpdateDownloader(QObject):
    """One download at a time, on its own thread.

    progress(received, total), finished(path), failed(reason). ``reason`` is
    one of the REASON_ constants (network failures may carry detail after a
    colon). After ``failed`` with a network reason, ``start`` again resumes.
    """

    progress = Signal(int, int)
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, parent=None, out_dir: Optional[str] = None):
        super().__init__(parent)
        self._out_dir = out_dir
        self._thread: Optional[QThread] = None
        self._worker: Optional[_Worker] = None

    def is_running(self) -> bool:
        return self._thread is not None

    def start(self, asset: dict) -> bool:
        """Begin, or resume, downloading ``asset``. False if one is running."""
        if self._thread is not None:
            return False
        self._thread = QThread(self)
        self._worker = _Worker(asset, self._out_dir)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self.progress)
        self._worker.done.connect(self._on_done)
        self._worker.done.connect(self._thread.quit)
        # The worker is released by dropping the reference after the thread
        # has ended (see UpdateChecker: a deleteLater posted on the worker
        # thread races the wrapper's own deletion).
        self._thread.finished.connect(self._cleanup)
        self._thread.start()
        return True

    def _on_done(self, path: str, reason: str) -> None:
        self._result = (path, reason)

    def _cleanup(self) -> None:
        thread = self._thread
        if thread is not None:
            thread.wait(2000)
        self._thread = None
        self._worker = None
        path, reason = getattr(self, "_result", ("", REASON_NETWORK))
        self._result = ("", REASON_NETWORK)
        if path:
            self.finished.emit(path)
        elif not reason.startswith(REASON_CANCELLED):
            self.failed.emit(reason)

    def shutdown(self) -> None:
        """Stop a download in flight before the app closes. The partial file
        stays for the next run."""
        if self._worker is not None:
            self._worker.cancel()
        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(3000)
