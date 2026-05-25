"""Disk-cached fetcher for Rendition pose pixmaps.

Verified pose names sourced from the TTR community wiki and probed
against rendition.toontownrewritten.com (HTTP 500 with invalid DNA
confirms the endpoint exists).

Cache: <config_dir>/rendition_cache/<dna>__<pose>__<size>.png
TTL:   24 hours (mtime-based). Expired entries refetch on access.

THREADING / PAINT-RACE NOTE
---------------------------
Per docs/postmortem-py314-gc-paint-segv.md (commits 1be26d4, 017eec2,
6b12fab), the Python 3.14 + Shiboken paint-time GC race is triggered
by high worker-side allocation rate during a main-thread paint
cascade. Mitigations in this module:

  * Bounded concurrency: max 3 worker threads via shared
    ThreadPoolExecutor.
  * Worker threads do HTTP + bytes only - NO QImage / QPixmap
    construction. Bytes are passed to the GUI thread via a private
    signal; decoding happens on the GUI thread.
  * No polling. Purely request-driven.
"""

from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Final, Optional

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage, QPixmap


POSE_NAMES: Final = (
    "portrait",
    "portrait-delighted",
    "portrait-grin",
    "portrait-thinking",
    "portrait-surprise",
    "portrait-sleep",
    "portrait-fall",
    "portrait-birthday",
    "head",
    "waving",
    "crying",
    "cake-topper",
    "laffmeter",
)

_TTL_SECONDS = 24 * 60 * 60
_MAX_WORKERS = 3
_REQUEST_SIZE = 512
_URL = (
    "https://rendition.toontownrewritten.com/render/{dna}/{pose}/"
    f"{_REQUEST_SIZE}x{_REQUEST_SIZE}.png"
)


class RenditionPoseFetcher(QObject):
    """Singleton: shared disk cache + bounded thread pool across all callers."""

    # Public signal: GUI-thread payload, ready-to-use QPixmap (or None on
    # failure). Internal _bytes_ready private signal stays inside this class.
    pose_ready = Signal(str, str, object)  # (dna, pose, QPixmap | None)
    # Private signal: worker thread emits bytes (no Qt object construction
    # on the worker side - see paint-race postmortem). The GUI-thread slot
    # decodes to QPixmap then re-emits the public pose_ready.
    _bytes_ready = Signal(str, str, object)  # (dna, pose, bytes | None)

    _instance: Optional["RenditionPoseFetcher"] = None
    _instance_lock = threading.Lock()

    @classmethod
    def instance(cls) -> "RenditionPoseFetcher":
        # Double-checked locking: matches utils/game_registry.py:43-57.
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        super().__init__()
        self._executor = ThreadPoolExecutor(max_workers=_MAX_WORKERS)
        from utils.build_flavor import config_dir as _config_dir
        self._cache_dir = os.path.join(_config_dir(), "rendition_cache")
        os.makedirs(self._cache_dir, exist_ok=True)
        try:
            os.chmod(self._cache_dir, 0o700)
        except OSError:
            pass
        self._cleanup_legacy_cache()
        self._bytes_ready.connect(self._on_bytes_ready)

    def cache_dir(self) -> str:
        return self._cache_dir

    def _cleanup_legacy_cache(self) -> None:
        """Remove old-format cache entries (pre-size-suffix). New format
        is <dna>__<pose>__<size>.png (two `__` separators); old format
        is <dna>__<pose>.png (one). Runs once per process from __init__.
        Touches only our own cache dir; failures are non-fatal."""
        try:
            names = os.listdir(self._cache_dir)
        except OSError:
            return
        for name in names:
            if not name.endswith(".png"):
                continue
            stem = name[:-4]
            if stem.count("__") == 1:
                try:
                    os.remove(os.path.join(self._cache_dir, name))
                except OSError:
                    pass

    # -- Disk cache ----------------------------------------------------------

    def _path_for(self, dna: str, pose: str) -> str:
        return os.path.join(
            self._cache_dir, f"{dna}__{pose}__{_REQUEST_SIZE}.png"
        )

    def cached_pixmap(self, dna: str, pose: str) -> Optional[QPixmap]:
        """Sync read. Returns pixmap if disk entry exists AND is fresh.
        None for missing, stale (mtime older than TTL), or unreadable."""
        path = self._path_for(dna, pose)
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return None
        import time as _time
        if _time.time() - mtime > _TTL_SECONDS:
            return None
        pm = QPixmap(path)
        return pm if not pm.isNull() else None

    # -- Async request -------------------------------------------------------

    def request(self, dna: str, pose: str) -> None:
        """Async. If disk cache is fresh, emits pose_ready immediately
        (via QTimer.singleShot(0) so receivers see a consistent
        GUI-thread firing). Otherwise queues a worker that fetches the
        PNG, writes it to disk, and emits via the private signal."""
        from PySide6.QtCore import QTimer
        if not dna or not pose:
            QTimer.singleShot(0, lambda d=dna, p=pose: self.pose_ready.emit(d, p, None))
            return
        cached = self.cached_pixmap(dna, pose)
        if cached is not None:
            QTimer.singleShot(
                0, lambda d=dna, p=pose, pm=cached: self.pose_ready.emit(d, p, pm)
            )
            return
        self._executor.submit(self._fetch_worker, dna, pose)

    def _fetch_worker(self, dna: str, pose: str) -> None:
        """Runs on a pool thread. NO Qt object construction here -
        bytes only. The GUI-thread slot decodes."""
        import urllib.request
        url = _URL.format(dna=dna, pose=pose)
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "ToonTown MultiTool"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = resp.read()
        except Exception:
            self._bytes_ready.emit(dna, pose, None)
            return
        # Write to disk before signaling so a same-thread reader sees the
        # bytes. Failure to write is non-fatal (we still emit the bytes).
        try:
            with open(self._path_for(dna, pose), "wb") as f:
                f.write(data)
        except OSError:
            pass
        self._bytes_ready.emit(dna, pose, data)

    def _on_bytes_ready(self, dna: str, pose: str, data) -> None:
        """GUI thread. Decode bytes -> QImage -> QPixmap, then emit public."""
        if data is None:
            self.pose_ready.emit(dna, pose, None)
            return
        img = QImage()
        if not img.loadFromData(bytes(data), "PNG"):
            self.pose_ready.emit(dna, pose, None)
            return
        pm = QPixmap.fromImage(img)
        self.pose_ready.emit(dna, pose, pm if not pm.isNull() else None)

    # -- Invalidate ----------------------------------------------------------

    def invalidate_dna(self, dna: str) -> None:
        """Remove all cache entries for `dna`. Called from the refresh
        button in the Toon section."""
        prefix = f"{dna}__"
        try:
            for name in os.listdir(self._cache_dir):
                if name.startswith(prefix):
                    try:
                        os.remove(os.path.join(self._cache_dir, name))
                    except OSError:
                        pass
        except OSError:
            pass
