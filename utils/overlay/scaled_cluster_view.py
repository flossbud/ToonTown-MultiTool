"""Whole-cluster QGraphicsView wrapper that zooms the borrowed host as one unit.

The borrowed ``_grid_host`` subtree (glow + 2x2 cards + emblem) is laid out ONCE
at its framed 1.0 size and proxied into a scene; a single item transform scales
it uniformly about the EMBLEM CENTER, which is pinned onto a fixed window-local
pivot. Scaling is therefore one ``setScale`` + repaint: no widget re-layout, no
per-element metric rounding, no window geometry change - every pixel of the
cluster (cards, chrome, emblem, glow) zooms on the same curve by construction.

Same proven mechanism as :class:`utils.overlay.scaled_card_view.ScaledCardView`
(and ``_FullLayout`` before it), widened from one card to the whole host, with
the pivot expressed on the ITEM (``setTransformOriginPoint`` + ``setPos``)
instead of the view transform so the view never fights QGraphicsView's
scene-alignment logic.

OWNERSHIP CONTRACT (load-bearing): the host is BORROWED, never owned. But
``QGraphicsScene.addWidget()`` transfers Qt ownership of the host to the proxy,
so the scene WOULD delete the host on destruction. Callers MUST call
``release_cluster()`` before deleting/closing this wrapper (it revokes the
proxy's ownership first). ``closeEvent()`` releases defensively as a safety net
for the ``close()`` path.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QGraphicsScene, QGraphicsView, QFrame,
)


class ScaledClusterView(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scale = 1.0
        self._host: QWidget | None = None
        self._proxy = None
        self._emblem_center = (0.0, 0.0)
        self._pivot = (0.0, 0.0)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._scene = QGraphicsScene(self)
        self._view = QGraphicsView(self._scene, self)
        # Embedded-widget update()s (the keep-alive SmoothProgressBar repainting
        # on each tick) must reliably reach the screen; the default partial
        # update mode can skip the proxied child's region (see ScaledCardView).
        self._view.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self._view.setRenderHints(
            QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing
        )
        self._view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._view.setFrameStyle(QFrame.NoFrame)
        # Scene rect == the fixed envelope (set at host time) and the view is
        # laid out to exactly that size, so alignment never has slack to apply;
        # top-left keeps the mapping origin-stable regardless.
        self._view.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        # Transparent viewport (4 mechanisms, matching ScaledCardView).
        self._view.setBackgroundBrush(Qt.transparent)
        self._view.setStyleSheet("QGraphicsView { background: transparent; border: none; }")
        self._view.setAttribute(Qt.WA_TranslucentBackground, True)
        self._view.viewport().setAutoFillBackground(False)
        lay.addWidget(self._view)

    def host(self) -> QWidget | None:
        return self._host

    def host_cluster(
        self,
        host: QWidget,
        emblem_center: tuple[float, float],
        pivot: tuple[float, float],
        envelope_size: tuple[int, int],
    ) -> None:
        """Proxy *host* (borrowed) into the scene, pivoted for envelope scaling.

        ``emblem_center`` is the zoom origin within the 1.0 host; ``pivot`` is
        the fixed window-local point that origin must occupy at every scale
        (both from ``cluster_geometry.envelope_for``). The proxy is positioned
        so ``scene = pivot + (host - emblem_center) * scale`` - identical math
        to ``map_host_rect_to_window``, so controller-side hit/shape mapping and
        the on-screen rendering can never drift apart.

        A previously hosted cluster is released (returned parentless) first.
        """
        if self._host is host:
            return
        if self._host is not None:
            self.release_cluster()
        ex, ey = float(emblem_center[0]), float(emblem_center[1])
        px, py = float(pivot[0]), float(pivot[1])
        self._emblem_center = (ex, ey)
        self._pivot = (px, py)
        self._scene.setSceneRect(0, 0, max(1, int(envelope_size[0])),
                                 max(1, int(envelope_size[1])))
        # addWidget() requires a TOP-LEVEL widget: it silently rejects a parented
        # one (proxy.widget() stays None). The borrowed host arrives detached
        # (capture_cluster_host reparents it to None), but detach defensively.
        host.setParent(None)
        self._host = host
        self._proxy = self._scene.addWidget(host)  # reparents host into the scene
        self._proxy.setTransformOriginPoint(QPointF(ex, ey))
        self._proxy.setPos(QPointF(px - ex, py - ey))
        self._apply_scale()

    def release_cluster(self) -> QWidget | None:
        """Un-proxy the borrowed host WITHOUT deleting it (ownership contract).

        Returns the host (parentless, undeleted) or None if nothing hosted.
        """
        host = self._host
        if host is None:
            return None
        if self._proxy is not None:
            self._proxy.setWidget(None)     # detach + un-own the host (NOT deleted)
            self._scene.removeItem(self._proxy)
            self._proxy = None
        # setWidget(None) already re-parented the host to None; explicit for clarity.
        host.setParent(None)
        self._host = None
        return host

    def closeEvent(self, ev):
        # Safety net: un-own the borrowed host before Qt's destruction cascade, so
        # the scene never deletes it on close() (see the ownership contract above).
        self.release_cluster()
        super().closeEvent(ev)

    def set_scale(self, scale: float) -> None:
        """Set the uniform zoom (one repaint; no re-layout, no geometry change)."""
        self._scale = float(scale)
        self._apply_scale()

    def scale(self) -> float:
        return self._scale

    def _apply_scale(self) -> None:
        if self._proxy is not None:
            # setScale REPLACES (never multiplies); the origin point makes it
            # scale about the emblem center, which setPos pinned on the pivot.
            self._proxy.setScale(self._scale)
