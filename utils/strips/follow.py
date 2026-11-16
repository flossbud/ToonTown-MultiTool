"""Keeps one strip surface on each tracked game window.

Owns the tracker, the attach strategy and the surfaces. What a strip SHOWS
is not decided here: the caller gets the surface back and feeds it models.
"""
from __future__ import annotations

import sys

from PySide6.QtCore import QObject, QTimer

from utils import settings_keys
from utils.overlay.backend import OverlayBackend, get_overlay_backend
from utils.strips import tokens
from utils.strips.attach import AttachStrategy, pick_attach_strategy
from utils.strips.strip_surface import StripSurface, strip_scale
from utils.strips.tracker import StripTracker

GATE_INTERVAL_MS = 100
# How often to ask whether a compositing manager came or went.
COMPOSITOR_CHECK_MS = 2000

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
                 size: str = settings_keys.FLOAT_STRIP_SIZE_SMALL,
                 parent: QObject | None = None) -> None:
        """`scale` replaces the true-size scale (the inverse of the app's UI
        scale) for a caller that knows better; the strip size's factor
        applies on top of either."""
        super().__init__(parent)
        self._strategy = strategy if strategy is not None else pick_attach_strategy()
        self._backend = backend if backend is not None else get_overlay_backend()
        self._style = tokens.style_for(style).name
        self._base_scale = scale
        self._size = settings_keys.normalize_float_strip_size(size)
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
        # Other surfaces of ours over the same windows (popovers): they never
        # occlude a strip, and they are swept by the same timer.
        self._extra_own = []       # callables returning window ids
        self._extra_sweeps = []    # callables taking (strategy, own ids)
        self._extra_refresh = []   # callables: the presentation mode changed

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
            print(f"[Strips] attach={self._strategy.name} style={self._style}"
                  f" size={self._size}"
                  + (" compositor=none (shaped windows)" if self._strategy.shaped() else ""),
                  flush=True)
        self._tracker.start()
        self._desktop = QTimer(self)
        self._desktop.setInterval(COMPOSITOR_CHECK_MS)
        self._desktop.timeout.connect(self.check_desktop)
        self._desktop.start()
        if self._strategy.gated:
            self._gate = QTimer(self)
            self._gate.setInterval(GATE_INTERVAL_MS)
            self._gate.timeout.connect(self._sweep)
            self._gate.start()

    def check_desktop(self) -> None:
        """Did translucency become available or go away? If so, every surface
        switches between translucent and shaped."""
        try:
            changed = self._strategy.refresh()
        except Exception:
            changed = False
        if not changed:
            return
        print(f"[Strips] compositing manager "
              f"{'gone: shaped windows' if self._strategy.shaped() else 'found: translucent windows'}",
              flush=True)
        for surface in self._surfaces.values():
            surface.refresh_presentation()
        for fn in self._extra_refresh:
            try:
                fn()
            except Exception:
                pass

    def stop(self) -> None:
        self._running = False
        desktop = getattr(self, "_desktop", None)
        if desktop is not None:
            desktop.stop()
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
            surface = StripSurface(self._strategy, self._backend, self.scale())
            surface.set_size_policy(self._size, self.scale() / settings_keys.float_strip_size_factor(self._size))
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

    def size(self) -> str:
        return self._size

    def scale(self) -> float:
        """Configured maximum scale; a narrow strip may step down a preset."""
        factor = settings_keys.float_strip_size_factor(self._size)
        if self._base_scale is None:
            return strip_scale(size=self._size)
        return float(self._base_scale) * factor

    def set_size(self, name: str) -> None:
        """Small, medium or large, applied to every strip where it stands."""
        size = settings_keys.normalize_float_strip_size(name)
        if size == self._size:
            return
        self._size = size
        scale = self.scale()
        for surface in self._surfaces.values():
            surface.set_size_policy(size, scale / settings_keys.float_strip_size_factor(size))

    def own_window_ids(self) -> list[int]:
        ids = [int(s.winId()) for s in self._surfaces.values() if s.isVisible()]
        for fn in self._extra_own:
            try:
                ids.extend(int(i) for i in fn())
            except Exception:
                pass
        return ids

    def add_companion(self, own_ids_fn, sweep_fn, refresh_fn=None) -> None:
        """Register surfaces that hang off the strips (see _extra_own)."""
        self._extra_own.append(own_ids_fn)
        self._extra_sweeps.append(sweep_fn)
        if refresh_fn is not None:
            self._extra_refresh.append(refresh_fn)

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
        for fn in self._extra_sweeps:
            try:
                fn(self._strategy, own)
            except Exception:
                pass
