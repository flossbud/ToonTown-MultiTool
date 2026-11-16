"""Fast geometry for the game windows that carry a strip.

The rule that makes following a window judder-free: a strip is never visible
while its window is moving or resizing. The tracker samples each window's
client rectangle about ten times a second. Any change hides the strip; two
identical samples in a row place it and show it again. Nothing chases the
window frame by frame.

WindowTrack is the pure state machine for one window. StripTracker samples
on a worker thread (a window-server round trip can take over 10 ms on
macOS) and reports on the GUI thread.
"""
from __future__ import annotations

import threading
from typing import Callable

from PySide6.QtCore import QObject, Signal

Rect = tuple  # (x, y, width, height) in the platform's native units

SAMPLE_INTERVAL_S = 0.1
STABLE_SAMPLES = 2

HIDE = "hide"
PLACE = "place"


class WindowTrack:
    """Decides, sample by sample, whether one window's strip may show."""

    def __init__(self, stable_samples: int = STABLE_SAMPLES) -> None:
        self._need = max(1, int(stable_samples))
        self._last: Rect | None = None
        self._count = 0
        self._placed: Rect | None = None   # where the strip is shown, if it is

    @property
    def placed(self) -> Rect | None:
        return self._placed

    def feed(self, rect: Rect | None):
        """Take one sample. Returns (HIDE, None), (PLACE, rect) or None when
        nothing changes. A missing or empty rectangle (window gone,
        minimized, off screen) hides the strip."""
        if rect is not None and (rect[2] <= 0 or rect[3] <= 0):
            rect = None
        if rect is None:
            self._last, self._count = None, 0
            if self._placed is not None:
                self._placed = None
                return (HIDE, None)
            return None
        rect = tuple(int(v) for v in rect)
        if rect != self._last:
            self._last, self._count = rect, 1
        else:
            self._count += 1
        if self._placed is not None and rect != self._placed:
            self._placed = None
            return (HIDE, None)
        if self._placed is None and self._count >= self._need:
            self._placed = rect
            return (PLACE, rect)
        return None

    def reset(self) -> None:
        """Forget everything: the next stable pair places the strip again."""
        self._last, self._count, self._placed = None, 0, None


class StripTracker(QObject):
    """Samples the tracked windows and tells the strips where to be.

    `geometry_fn(window_id)` returns the client rectangle in native units or
    None; it runs on the sampling thread.
    """

    place = Signal(str, object)    # window id, (x, y, w, h)
    hide = Signal(str)             # moving, resized, minimized or gone
    _sampled = Signal(object)      # (run, membership, samples), thread -> GUI

    def __init__(self, geometry_fn: Callable[[str], Rect | None] | None = None,
                 interval_s: float = SAMPLE_INTERVAL_S,
                 parent: QObject | None = None,
                 batch_fn: Callable[[tuple], dict] | None = None) -> None:
        """`batch_fn(window_ids)` replaces per-window calls where one query
        answers for every window (macOS: one window-list round trip)."""
        super().__init__(parent)
        self._geometry_fn = geometry_fn
        self._batch_fn = batch_fn
        self._interval = float(interval_s)
        self._tracks: dict[str, WindowTrack] = {}
        self._wids: tuple[str, ...] = ()       # read by the sampling thread
        self._request = (0, self._wids)        # immutable snapshot for the worker
        self._generation = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._sampled.connect(self._receive_sample)

    # -- GUI thread ---------------------------------------------------------

    def set_windows(self, window_ids) -> None:
        wids = tuple(str(w) for w in window_ids)
        if wids == self._wids:
            return
        for wid in list(self._tracks):
            if wid not in wids:
                del self._tracks[wid]
        for wid in wids:
            self._tracks.setdefault(wid, WindowTrack())
        self._wids = wids
        self._request = (self._request[0] + 1, wids)

    def windows(self) -> tuple[str, ...]:
        return self._wids

    def placed_rect(self, window_id: str) -> Rect | None:
        track = self._tracks.get(str(window_id))
        return track.placed if track else None

    def invalidate(self, window_id: str | None = None) -> None:
        """Make the tracker place a strip again even though its window has
        not moved (the strip changed size, or its surface was recreated)."""
        for wid, track in self._tracks.items():
            if window_id is None or wid == str(window_id):
                track.reset()
        self._request = (self._request[0] + 1, self._wids)

    def start(self) -> None:
        if (self._thread is not None and self._thread.is_alive()
                and not self._stop.is_set()):
            return
        # Never clear the event a slow, stopped worker still holds.
        self._stop = threading.Event()
        self._generation += 1
        self._thread = threading.Thread(target=self._run,
                                        args=(self._stop, self._generation),
                                        name="strip-tracker",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._generation += 1
        thread, self._thread = self._thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)

    def sample_now(self) -> None:
        """One synchronous sample on the calling thread (tests, and the
        first placement so a new strip does not wait for the thread)."""
        self._on_sampled(self._sample(self._wids))

    def _on_sampled(self, samples: dict) -> None:
        for wid, rect in samples.items():
            track = self._tracks.get(wid)
            if track is None:
                continue          # untracked since the sample was taken
            action = track.feed(rect)
            if action is None:
                continue
            if action[0] == PLACE:
                self.place.emit(wid, action[1])
            else:
                self.hide.emit(wid)

    def _receive_sample(self, result) -> None:
        generation, revision, samples = result
        if generation != self._generation or revision != self._request[0]:
            return
        self._on_sampled(samples)

    # -- sampling thread ----------------------------------------------------

    def _sample(self, wids) -> dict:
        if self._batch_fn is not None:
            try:
                got = self._batch_fn(tuple(wids)) or {}
            except Exception:
                got = {}
            return {wid: got.get(wid) for wid in wids}
        out = {}
        for wid in wids:
            try:
                out[wid] = self._geometry_fn(wid)
            except Exception:
                out[wid] = None
        return out

    def _run(self, stop: threading.Event, generation: int) -> None:
        while not stop.is_set():
            revision, wids = self._request
            if wids:
                samples = self._sample(wids)
                if stop.is_set():
                    break
                try:
                    self._sampled.emit((generation, revision, samples))
                except RuntimeError:
                    break         # the QObject is gone: the app is closing
            stop.wait(self._interval)
