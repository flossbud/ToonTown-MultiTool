"""Disk-cached fetcher for Rendition pose pixmaps.

Verified pose names sourced from the TTR community wiki and probed
against rendition.toontownrewritten.com (HTTP 500 with invalid DNA
confirms the endpoint exists).

Cache: <config_dir>/rendition_cache/<dna>__<pose>.png
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
# QImage / QPixmap imports land in Task 2 where the GUI-thread decode happens.


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
_URL = "https://rendition.toontownrewritten.com/render/{dna}/{pose}/128x128.png"


class RenditionPoseFetcher(QObject):
    """Singleton: shared disk cache + bounded thread pool across all callers."""

    # Public signal: GUI-thread payload, ready-to-use QPixmap (or None on
    # failure). Internal _bytes_ready private signal stays inside this class.
    pose_ready = Signal(str, str, object)  # (dna, pose, QPixmap | None)

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

    def cache_dir(self) -> str:
        return self._cache_dir
