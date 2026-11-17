"""Toon portraits for the strips, from the same render store the launcher
cards use.

A lookup can read a manifest from disk and queue a fetch, so nothing here
runs while painting: the controller asks when a toon changes and when a
render lands, and the answer is remembered until then. No render (Corporate
Clash, no DNA yet, not fetched yet) is None, and the strip paints the tinted
silhouette instead.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QPixmap

from utils.toon_customization_resolve import (resolve_portrait_transform,
                                              resolve_pose)

DEFAULT_POSE = "portrait"
_MISSING = object()


class PortraitProvider(QObject):
    changed = Signal(str, str)        # game, toon name: a portrait may differ now

    def __init__(self, renders=None, customizations=None,
                 parent: QObject | None = None) -> None:
        """`renders` is a ToonRenders (the app's shared one when None);
        `customizations` the looks store, which picks the pose."""
        super().__init__(parent)
        self._renders = renders
        self._customizations = customizations
        self._cache: dict[tuple[str, str], object] = {}
        self._wired = False
        self._connections = []
        self._closed = False

    def _store(self):
        if self._renders is None:
            from utils.toon_renders import ToonRenders
            self._renders = ToonRenders.instance()
        if not self._wired:
            self._wired = True
            self._connections.append(self._renders.render_landed.connect(self._render_landed))
            self._connections.append(self._renders.set_promoted.connect(self._invalidate))
        return self._renders

    def _render_landed(self, game: str, name: str, _pose: str) -> None:
        self._invalidate(game, name)

    def shutdown(self) -> None:
        self._closed = True
        for connection in self._connections:
            try:
                QObject.disconnect(connection)
            except (RuntimeError, TypeError):
                pass
        self._connections.clear()
        self._cache.clear()

    def _invalidate(self, game: str, name: str) -> None:
        if self._closed:
            return
        self._cache.pop((game, name), None)
        self.changed.emit(game, name)

    def forget(self, game: str, name: str) -> None:
        """The toon's look changed (pose, outfit): look it up again."""
        self._cache.pop((game, name), None)

    def _look(self, game: str, name: str) -> dict:
        if self._customizations is None:
            return {}
        try:
            return self._customizations.get(game, name) or {}
        except Exception:
            return {}

    def pose_for(self, game: str, name: str) -> str:
        return resolve_pose(self._look(game, name), DEFAULT_POSE)

    def frame(self, toon) -> tuple:
        """The saved framing of the toon's portrait: (zoom, offset x,
        offset y, rotation). A cheap in-memory read."""
        if not toon.name:
            return (1.0, 0.0, 0.0, 0.0)
        try:
            return tuple(resolve_portrait_transform(self._look(toon.game, toon.name)))
        except (TypeError, ValueError):
            return (1.0, 0.0, 0.0, 0.0)

    def pixmap(self, toon) -> QPixmap | None:
        """The portrait for a ToonState, or None for the silhouette."""
        if self._closed or not toon.name or toon.game != "ttr" or not toon.dna:
            return None
        key = (toon.game, toon.name)
        hit = self._cache.get(key, _MISSING)
        if hit is not _MISSING:
            return hit
        try:
            got = self._store().pixmap_for(toon.game, toon.name,
                                           self.pose_for(toon.game, toon.name))
        except Exception:
            got = None
        pixmap = got[0] if got else None
        self._cache[key] = pixmap
        return pixmap
