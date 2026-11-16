"""Keeps one strip surface on each tracked game window.

Owns the tracker, the attach strategy and the surfaces. What a strip SHOWS
is not decided here: the caller gets the surface back and feeds it models.
"""
from __future__ import annotations

import sys

from PySide6.QtCore import QObject, QTimer

from utils.overlay.backend import OverlayBackend, get_overlay_backend
from utils.strips import tokens
from utils.strips.attach import AttachStrategy, pick_attach_strategy
from utils.strips.strip_surface import StripSurface
from utils.strips.tracker import StripTracker

GATE_INTERVAL_MS = 100

_stamped = False


def _platform_geometry(wid: str):
    from services.window_manager import _geometry_backend
    return _geometry_backend().get_window_geometry(wid)


def _darwin_batch(wids: tuple) -> dict:
    """Every tracked window's content rectangle from ONE window-list query."""
    from utils import macos_discovery
    wanted = {str(w) for w in wids}
    out = {}
    for record in macos_discovery._enumerate_game_windows_uncached():
        wid = str(record.window_id)
        if wid in wanted:
            out[wid] = record.bounds
    return out


class StripFollower(QObject):
    def __init__(self, strategy: AttachStrategy | None = None,
                 backend: OverlayBackend | None = None,
                 geometry_fn=None, batch_fn=None, style: str = tokens.NEON,
                 scale: float | None = None,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._strategy = strategy if strategy is not None else pick_attach_strategy()
        self._backend = backend if backend is not None else get_overlay_backend()
        self._style = tokens.style_for(style).name
        self._scale = scale
        self._surfaces: dict[str, StripSurface] = {}
        if geometry_fn is None and batch_fn is None:
            if sys.platform == "darwin":
                batch_fn = _darwin_batch
            else:
                geometry_fn = _platform_geometry
        self._tracker = StripTracker(geometry_fn, parent=self, batch_fn=batch_fn)
        self._tracker.place.connect(self._on_place)
        self._tracker.hide.connect(self._on_hide)
        self._gate: QTimer | None = None
        self._running = False

    # -- lifecycle ----------------------------------------------------------

    @property
    def strategy(self) -> AttachStrategy:
        return self._strategy

    @property
    def tracker(self) -> StripTracker:
        return self._tracker

    def start(self) -> None:
        global _stamped
        if self._running:
            return
        self._running = True
        if not _stamped:
            _stamped = True
            print(f"[Strips] attach={self._strategy.name} style={self._style}",
                  flush=True)
        self._tracker.start()
        if self._strategy.gated:
            self._gate = QTimer(self)
            self._gate.setInterval(GATE_INTERVAL_MS)
            self._gate.timeout.connect(self._sweep)
            self._gate.start()

    def stop(self) -> None:
        self._running = False
        self._tracker.stop()
        if self._gate is not None:
            self._gate.stop()
            self._gate = None

    def shutdown(self) -> None:
        self.stop()
        for wid in list(self._surfaces):
            self.remove(wid)

    # -- strips -------------------------------------------------------------

    def surfaces(self) -> dict[str, StripSurface]:
        return dict(self._surfaces)

    def surface(self, window_id: str) -> StripSurface | None:
        return self._surfaces.get(str(window_id))

    def add(self, window_id: str) -> StripSurface:
        wid = str(window_id)
        surface = self._surfaces.get(wid)
        if surface is None:
            surface = StripSurface(self._strategy, self._backend, self._scale)
            surface.set_style(self._style)
            surface.set_game_window(wid)
            self._surfaces[wid] = surface
            self._tracker.set_windows(self._surfaces)
        return surface

    def remove(self, window_id: str) -> None:
        surface = self._surfaces.pop(str(window_id), None)
        self._tracker.set_windows(self._surfaces)
        if surface is not None:
            surface.hide()
            surface.deleteLater()

    def set_style(self, name: str) -> None:
        self._style = tokens.style_for(name).name
        for surface in self._surfaces.values():
            surface.set_style(self._style)

    def own_window_ids(self) -> list[int]:
        return [int(s.winId()) for s in self._surfaces.values() if s.isVisible()]

    # -- tracker ------------------------------------------------------------

    def _on_place(self, wid: str, rect) -> None:
        surface = self._surfaces.get(wid)
        if surface is not None:
            surface.place(rect)
            if self._strategy.gated:
                self._gate_one(wid, surface, self.own_window_ids())

    def _on_hide(self, wid: str) -> None:
        surface = self._surfaces.get(wid)
        if surface is not None:
            surface.conceal()

    # -- gate ---------------------------------------------------------------

    def _gate_one(self, wid: str, surface: StripSurface, own) -> None:
        try:
            region = self._strategy.visible_region(surface.geometry(), wid, own)
        except Exception:
            region = None
        surface.set_visible_region(region)

    def _sweep(self) -> None:
        own = self.own_window_ids()
        for wid, surface in self._surfaces.items():
            if surface.isVisible() and self._tracker.placed_rect(wid) is not None:
                self._gate_one(wid, surface, own)
