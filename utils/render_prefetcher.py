# utils/render_prefetcher.py
"""Downloads renders into the per-toon store, ahead of need.

Owns the queue, a small in-flight cap so a stalled origin cannot starve warm
work, priority (an on-screen `want` beats a speculative sweep), and a circuit
breaker: three consecutive timeout/5xx events stop all downloads; a single
probe retries on a backoff; one success closes the breaker and drains the
queue. Store mutations and signal emissions happen on the GUI thread only —
workers hand back bytes or an error through a queued signal.
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from typing import Iterable, Optional

from PySide6.QtCore import QObject, Qt, QTimer, Signal

from utils.rendition_poses import BREAKER_KINDS, DownloadError, download_pose
from utils.toon_render_store import ToonRenderStore

PRIORITY_WANT = 0
PRIORITY_DISCOVERED = 1
PRIORITY_SWEEP = 2
BREAKER_THRESHOLD = 3
BACKOFF_S = (30, 60, 120, 300)

_Key = tuple[str, str, str, str]   # game, name, dna, pose


class RenderPrefetcher(QObject):
    render_landed = Signal(str, str, str)      # game, name, pose
    set_promoted = Signal(str, str)            # game, name
    breaker_changed = Signal(bool)             # True = open (paused)
    # worker -> GUI thread. Always queued so a synchronous executor in tests
    # still delivers on processEvents, never re-entrantly inside submit().
    _result = Signal(str, str, str, str, object, object)

    def __init__(self, store: ToonRenderStore, downloader=download_pose,
                 executor=None, max_in_flight: int = 3,
                 backoff_s: tuple[int, ...] = BACKOFF_S, parent=None) -> None:
        super().__init__(parent)
        self._store = store
        self._download = downloader
        self._executor = executor or ThreadPoolExecutor(max_workers=max_in_flight)
        self._max = max_in_flight
        self._backoff = tuple(backoff_s)
        self._queue: dict[_Key, tuple[int, int]] = {}   # key -> (priority, seq)
        self._in_flight: set[_Key] = set()
        self._seq = 0
        self._consecutive = 0
        self._open = False
        self._backoff_i = 0
        self._probe_key: Optional[_Key] = None
        self._probe = QTimer(self)
        self._probe.setSingleShot(True)
        self._probe.timeout.connect(self.fire_probe_now)
        self._result.connect(self._on_result, Qt.QueuedConnection)

    # ── inbound ────────────────────────────────────────────────────────────

    def discovered(self, game: str, name: str, dna: str) -> None:
        self._enqueue_missing(game, name, dna, PRIORITY_DISCOVERED)

    def sweep(self, toons: Iterable[tuple[str, str, str]]) -> None:
        for game, name, dna in toons:
            self._enqueue_missing(game, name, dna, PRIORITY_SWEEP)

    def want(self, game: str, name: str, pose: str) -> None:
        """A consumer needs this pose on screen now: front of the queue."""
        dna = self._store.candidate_dna(game, name) or self._store.current_dna(game, name)
        if not dna or pose not in self._store.missing_poses(game, name, dna):
            return
        self._enqueue((game, name, dna, pose), PRIORITY_WANT)

    def invalidate(self, game: str, name: str) -> None:
        dna = self._store.invalidate(game, name)
        if dna:
            self._enqueue_missing(game, name, dna, PRIORITY_WANT)

    # ── state ──────────────────────────────────────────────────────────────

    @property
    def breaker_open(self) -> bool:
        return self._open

    @property
    def pending_count(self) -> int:
        return len(self._queue)

    @property
    def in_flight_count(self) -> int:
        return len(self._in_flight)

    @property
    def probe_interval_ms(self) -> int:
        return self._probe.interval()

    # ── queue ──────────────────────────────────────────────────────────────

    def _enqueue_missing(self, game: str, name: str, dna: str, priority: int) -> None:
        if not dna or not name:
            return
        if self._store.note_dna(game, name, dna) == "current":
            return
        for pose in self._store.missing_poses(game, name, dna):
            self._enqueue((game, name, dna, pose), priority)

    def _enqueue(self, key: _Key, priority: int) -> None:
        if key in self._in_flight:
            return
        prev = self._queue.get(key)
        if prev is None:
            self._seq += 1
            self._queue[key] = (priority, self._seq)
        elif priority < prev[0]:
            self._queue[key] = (priority, prev[1])
        self._pump()

    def _next_key(self) -> Optional[_Key]:
        if not self._queue:
            return None
        return min(self._queue, key=self._queue.__getitem__)

    def _pump(self) -> None:
        if self._open:
            return
        while len(self._in_flight) < self._max:
            key = self._next_key()
            if key is None:
                return
            self._submit(key)

    def _submit(self, key: _Key) -> None:
        self._queue.pop(key, None)
        self._in_flight.add(key)
        self._executor.submit(self._worker, *key)

    def _worker(self, game: str, name: str, dna: str, pose: str) -> None:
        """Pool thread. Bytes or an error — never a Qt object, never the store."""
        try:
            data = self._download(dna, pose)
        except DownloadError as exc:
            self._result.emit(game, name, dna, pose, None, exc)
            return
        except Exception as exc:                       # noqa: BLE001
            self._result.emit(game, name, dna, pose, None,
                              DownloadError("other", None, str(exc)))
            return
        self._result.emit(game, name, dna, pose, data, None)

    # ── results (GUI thread) ───────────────────────────────────────────────

    def _on_result(self, game: str, name: str, dna: str, pose: str,
                   data, err) -> None:
        key = (game, name, dna, pose)
        self._in_flight.discard(key)
        was_probe = key == self._probe_key
        self._probe_key = None

        if err is None:
            path = self._store.path_for(game, name, dna, pose)
            tmp = path + ".part"
            try:
                # Atomic: a crash mid-write must not leave a truncated PNG
                # whose header still passes the store's validity check.
                with open(tmp, "wb") as f:
                    f.write(data)
                os.replace(tmp, path)
            except OSError as exc:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                err = DownloadError("other", None, f"write failed: {exc}")
            else:
                if self._store.mark_landed(game, name, dna, pose):
                    self._consecutive = 0
                    if self._open:
                        self._close_breaker()
                    self.render_landed.emit(game, name, pose)
                    if self._store.promote_if_complete(game, name):
                        self.set_promoted.emit(game, name)
                    self._pump()
                    return
                err = DownloadError("server", None, "body was not a valid PNG")

        if err.kind == "client":
            self._store.mark_failed(game, name, dna, pose)
            self._consecutive = 0
            self._pump()
            return

        # A breaker event (timeout / 5xx / other): keep the work, count it.
        self._enqueue_silently(key)
        self._consecutive += 1
        if was_probe:
            self._backoff_i = min(self._backoff_i + 1, len(self._backoff) - 1)
            self._schedule_probe()
        elif not self._open and self._consecutive >= BREAKER_THRESHOLD:
            self._open_breaker()
        else:
            self._pump()

    def _enqueue_silently(self, key: _Key) -> None:
        if key not in self._queue:
            self._seq += 1
            self._queue[key] = (PRIORITY_WANT, self._seq)   # retried first once open

    # ── breaker ────────────────────────────────────────────────────────────

    def _open_breaker(self) -> None:
        self._open = True
        self._backoff_i = 0
        self.breaker_changed.emit(True)
        self._schedule_probe()

    def _close_breaker(self) -> None:
        self._open = False
        self._backoff_i = 0
        self._consecutive = 0
        self._probe.stop()
        self.breaker_changed.emit(False)

    def _schedule_probe(self) -> None:
        self._probe.start(self._backoff[self._backoff_i] * 1000)

    def fire_probe_now(self) -> None:
        """Send exactly one queued download past the open breaker. On success
        the breaker closes and the queue drains; on failure the backoff grows."""
        self._probe.stop()
        if not self._open or self._in_flight:
            return
        key = self._next_key()
        if key is None:
            self._close_breaker()
            return
        self._probe_key = key
        self._submit(key)
